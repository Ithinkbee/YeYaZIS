"""Чтение из других программ Windows: буфер обмена и горячие клавиши.

Методичка требует, чтобы текст можно было взять не только из поля ввода,
но и из буфера обмена или указателем мыши в другом приложении. Здесь — та
часть, что работает в любой программе Windows, а не только в браузере:

* **слежение за буфером обмена.** Пока оно включено, всё, что
  скопировано в любой программе (Ctrl+C в Word, в PDF, на веб-странице),
  сразу читается вслух. Система спрашивает у Windows номер версии буфера
  (GetClipboardSequenceNumber) трижды в секунду и читает текст, только когда
  номер изменился;
* **горячая клавиша Ctrl+Alt+R** — «прочитать выделенное»: выделите текст
  мышью в любой программе и нажмите сочетание. Система дожидается, пока
  отпущены Ctrl и Alt, сама нажимает за пользователя Ctrl+C, забирает
  скопированное и возвращает в буфер то, что лежало там раньше, — буфер
  пользователя не портится. Ctrl+Alt+S — замолчать.

Прочитанное звучит на странице «Чтец», если она открыта (и там же видно,
что читается), а без неё — прямо из колонок компьютера (winsound).

Всё сделано на ctypes — вызовами user32.dll и kernel32.dll, без
дополнительных пакетов. В других системах модуль сообщает, что
недоступен.
"""

from __future__ import annotations

import logging
import sys
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from glashatai import config

log = logging.getLogger("glashatai.desktop")

SUPPORTED = sys.platform == "win32"

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002
WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN = 0x11, 0x12, 0x10, 0x5B
KEYEVENTF_KEYUP = 0x0002

if SUPPORTED:
    import ctypes
    from ctypes import wintypes

    _user32 = ctypes.WinDLL("user32", use_last_error=True)
    _kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

    _user32.OpenClipboard.argtypes = [wintypes.HWND]
    _user32.OpenClipboard.restype = wintypes.BOOL
    _user32.CloseClipboard.restype = wintypes.BOOL
    _user32.EmptyClipboard.restype = wintypes.BOOL
    _user32.GetClipboardData.argtypes = [wintypes.UINT]
    _user32.GetClipboardData.restype = wintypes.HANDLE
    _user32.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    _user32.SetClipboardData.restype = wintypes.HANDLE
    _user32.IsClipboardFormatAvailable.argtypes = [wintypes.UINT]
    _user32.IsClipboardFormatAvailable.restype = wintypes.BOOL
    _user32.GetClipboardSequenceNumber.restype = wintypes.DWORD
    _user32.RegisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int, wintypes.UINT, wintypes.UINT]
    _user32.RegisterHotKey.restype = wintypes.BOOL
    _user32.UnregisterHotKey.argtypes = [wintypes.HWND, ctypes.c_int]
    _user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
    _user32.GetMessageW.restype = ctypes.c_int
    _user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
    _user32.keybd_event.argtypes = [wintypes.BYTE, wintypes.BYTE, wintypes.DWORD, ctypes.c_size_t]
    _user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    _user32.GetAsyncKeyState.restype = ctypes.c_short
    _kernel32.GlobalLock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalLock.restype = wintypes.LPVOID
    _kernel32.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    _kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    _kernel32.GlobalAlloc.restype = wintypes.HGLOBAL
    _kernel32.GetCurrentThreadId.restype = wintypes.DWORD


# --- буфер обмена ------------------------------------------------------------------------------

def _open(attempts: int = 10) -> bool:
    """Буфер может быть занят другой программой — несколько попыток."""
    for _ in range(attempts):
        if _user32.OpenClipboard(None):
            return True
        time.sleep(0.02)
    return False


def sequence() -> int:
    return int(_user32.GetClipboardSequenceNumber()) if SUPPORTED else 0


def read_clipboard() -> str | None:
    """Текст из буфера обмена или None, если там не текст."""
    if not SUPPORTED or not _open():
        return None
    try:
        if not _user32.IsClipboardFormatAvailable(CF_UNICODETEXT):
            return None
        handle = _user32.GetClipboardData(CF_UNICODETEXT)
        if not handle:
            return None
        pointer = _kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            _kernel32.GlobalUnlock(handle)
    finally:
        _user32.CloseClipboard()


def write_clipboard(text: str) -> bool:
    if not SUPPORTED or not _open():
        return False
    try:
        _user32.EmptyClipboard()
        data = ctypes.create_unicode_buffer(text)
        size = ctypes.sizeof(data)
        handle = _kernel32.GlobalAlloc(GMEM_MOVEABLE, size)
        if not handle:
            return False
        pointer = _kernel32.GlobalLock(handle)
        ctypes.memmove(pointer, data, size)
        _kernel32.GlobalUnlock(handle)
        return bool(_user32.SetClipboardData(CF_UNICODETEXT, handle))
    finally:
        _user32.CloseClipboard()


# --- горячие клавиши -----------------------------------------------------------------------------

def parse_hotkey(text: str) -> tuple[int, int]:
    """«Ctrl+Alt+R» -> (модификаторы, код клавиши)."""
    modifiers = MOD_NOREPEAT
    key = 0
    for part in text.replace(" ", "").split("+"):
        lower = part.lower()
        if lower in {"ctrl", "control", "strg"}:
            modifiers |= MOD_CONTROL
        elif lower == "alt":
            modifiers |= MOD_ALT
        elif lower == "shift":
            modifiers |= MOD_SHIFT
        elif lower in {"win", "windows"}:
            modifiers |= MOD_WIN
        elif len(part) == 1 and part.isalnum():
            key = ord(part.upper())
        elif lower.startswith("f") and lower[1:].isdigit():
            key = 0x6F + int(lower[1:])
    if not key:
        raise ValueError(f"не понимаю сочетание клавиш «{text}»")
    return modifiers, key


def _modifiers_down() -> bool:
    return any(_user32.GetAsyncKeyState(code) & 0x8000 for code in (VK_CONTROL, VK_MENU, VK_SHIFT, VK_LWIN))


def copy_selection(timeout: float = 0.8) -> str | None:
    """Выделенное в активной программе: нажать Ctrl+C за пользователя и забрать текст.

    Прежнее содержимое буфера возвращается на место.
    """
    deadline = time.time() + 1.5
    while _modifiers_down() and time.time() < deadline:
        time.sleep(0.02)            # пока держат Ctrl+Alt, наш Ctrl+C стал бы Ctrl+Alt+C
    saved = read_clipboard()
    before = sequence()
    _user32.keybd_event(VK_CONTROL, 0, 0, 0)
    _user32.keybd_event(ord("C"), 0, 0, 0)
    _user32.keybd_event(ord("C"), 0, KEYEVENTF_KEYUP, 0)
    _user32.keybd_event(VK_CONTROL, 0, KEYEVENTF_KEYUP, 0)
    end = time.time() + timeout
    while sequence() == before and time.time() < end:
        time.sleep(0.02)
    if sequence() == before:
        return None
    text = read_clipboard()
    if saved is not None:
        write_clipboard(saved)
    return text


# --- воспроизведение без браузера -------------------------------------------------------------------

class LocalPlayer:
    """Звук прямо из колонок: winsound проигрывает WAV-файл асинхронно."""

    def __init__(self) -> None:
        self.folder = Path(tempfile.mkdtemp(prefix="glashatai-play-"))
        self._counter = 0

    def play(self, wav: bytes) -> None:
        if not SUPPORTED:
            return
        import winsound

        self._counter += 1
        path = self.folder / f"say-{self._counter % 4}.wav"
        winsound.PlaySound(None, 0)
        path.write_bytes(wav)
        winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)

    def stop(self) -> None:
        if SUPPORTED:
            import winsound

            winsound.PlaySound(None, 0)


# --- всё вместе -------------------------------------------------------------------------------------

@dataclass
class DesktopState:
    supported: bool = SUPPORTED
    clipboard: bool = False         # следить за буфером обмена
    hotkeys: bool = False           # горячие клавиши зарегистрированы
    hotkey_read: str = config.HOTKEY_READ
    hotkey_stop: str = config.HOTKEY_STOP
    problem: str = ""
    events: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"supported": self.supported, "clipboard": self.clipboard, "hotkeys": self.hotkeys,
                "hotkey_read": self.hotkey_read, "hotkey_stop": self.hotkey_stop, "problem": self.problem,
                "events": self.events[-12:]}


class Desktop:
    """Слежение за буфером и горячие клавиши; прочитанное уходит в on_text."""

    def __init__(self, on_text: Callable[[str, str], None], on_stop: Callable[[], None]) -> None:
        self.on_text = on_text
        self.on_stop = on_stop
        self.state = DesktopState()
        self._stop = threading.Event()
        self._watcher: threading.Thread | None = None
        self._hotkey_thread: threading.Thread | None = None
        self._hotkey_thread_id = 0
        self._ignore_until = 0          # номер буфера, изменения до которого сделаны самой системой
        self._last_text = ""

    def note(self, kind: str, text: str) -> None:
        self.state.events.append({"time": time.strftime("%H:%M:%S"), "kind": kind,
                                  "text": text[:160] + ("…" if len(text) > 160 else "")})
        del self.state.events[:-30]

    # --- буфер ---------------------------------------------------------------------------------

    def set_clipboard(self, enabled: bool) -> None:
        if not SUPPORTED:
            self.state.problem = "Слежение за буфером обмена работает только в Windows."
            return
        self.state.clipboard = enabled
        if enabled:
            # то, что уже лежит в буфере, читать не нужно — только новое
            self._ignore_until = sequence()
            if self._watcher is None or not self._watcher.is_alive():
                self._stop.clear()
                self._watcher = threading.Thread(target=self._watch, name="clipboard", daemon=True)
                self._watcher.start()

    def _watch(self) -> None:
        last = sequence()
        while not self._stop.is_set():
            time.sleep(config.CLIPBOARD_POLL_SECONDS)
            if not self.state.clipboard:
                last = sequence()
                continue
            current = sequence()
            if current == last:
                continue
            last = current
            if current <= self._ignore_until:
                continue
            text = read_clipboard()
            if not text or not text.strip() or text == self._last_text:
                continue
            self._last_text = text
            self._deliver(text, "clipboard")

    def _deliver(self, text: str, source: str) -> None:
        text = text.strip()[: config.MAX_CLIPBOARD_CHARS]
        self.note(source, text)
        try:
            self.on_text(text, source)
        except Exception as problem:            # noqa: BLE001
            log.warning("не удалось прочитать текст из другой программы: %s", problem)

    # --- горячие клавиши ----------------------------------------------------------------------

    def set_hotkeys(self, enabled: bool) -> None:
        if not SUPPORTED:
            self.state.problem = "Горячие клавиши работают только в Windows."
            return
        if enabled and not self.state.hotkeys:
            ready = threading.Event()
            self._hotkey_thread = threading.Thread(target=self._hotkey_loop, args=(ready,), name="hotkeys",
                                                   daemon=True)
            self._hotkey_thread.start()
            ready.wait(3)
        elif not enabled and self.state.hotkeys and self._hotkey_thread_id:
            _user32.PostThreadMessageW(self._hotkey_thread_id, WM_QUIT, 0, 0)
            if self._hotkey_thread is not None:
                self._hotkey_thread.join(2)
            self.state.hotkeys = False

    def _hotkey_loop(self, ready: threading.Event) -> None:
        self._hotkey_thread_id = _kernel32.GetCurrentThreadId()
        registered = []
        try:
            for number, combo in ((1, self.state.hotkey_read), (2, self.state.hotkey_stop)):
                modifiers, key = parse_hotkey(combo)
                if _user32.RegisterHotKey(None, number, modifiers, key):
                    registered.append(number)
            if 1 not in registered:
                self.state.problem = (f"Сочетание {self.state.hotkey_read} уже занято другой программой — "
                                      "горячая клавиша не работает.")
                self.state.hotkeys = False
                ready.set()
                return
            self.state.problem = ""
            self.state.hotkeys = True
            ready.set()
            message = wintypes.MSG()
            while _user32.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:
                if message.message != WM_HOTKEY:
                    continue
                if message.wParam == 1:
                    threading.Thread(target=self._read_selection, daemon=True).start()
                elif message.wParam == 2:
                    self.note("stop", "замолчать")
                    self.on_stop()
        finally:
            for number in registered:
                _user32.UnregisterHotKey(None, number)
            self.state.hotkeys = False
            ready.set()

    def _read_selection(self) -> None:
        text = copy_selection()
        # система сама меняла буфер — эти изменения слежение не читает
        self._ignore_until = sequence()
        if text and text.strip():
            self._deliver(text, "selection")
        else:
            self.note("empty", "ничего не выделено")

    def close(self) -> None:
        self._stop.set()
        self.set_hotkeys(False)
        self.state.clipboard = False
