"""Вход администратора.

Обычный пользователь говорит с системой, но не может менять фразы-пасхалки:
это право администратора. Администратор входит по имени и паролю (ссылка
«Вход администратора» внизу любой страницы или адрес /admin). Имя и пароль
задаются при запуске системы — переменными SLUHACH_ADMIN_LOGIN и
SLUHACH_ADMIN_PASSWORD или ключом --admin-password.

После верного входа сервер выдаёт случайный ключ сеанса и кладёт его в
cookie, недоступную сценариям страницы; без этого ключа сервер не показывает
и не меняет пасхалки. Поэтому обычный пользователь, даже открыв окно
администратора, увидит в нём только вопрос об имени и пароле. Ключи сеансов
живут в памяти: после перезапуска системы нужно войти заново.
"""

from __future__ import annotations

import hmac
import secrets
import threading
import time

from sluhach import config

COOKIE = "sluhach_admin"


class AdminError(Exception):
    """Вход не выполнен; текст показывается в окне."""


def _same(given: str, expected: str) -> bool:
    """Сравнение за постоянное время: по длительности ответа строку не подобрать."""
    return hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


class Admin:
    def __init__(self, password: str | None = None, name: str | None = None, clock=time.monotonic) -> None:
        self._name = (config.ADMIN_LOGIN if name is None else name).strip().lower()
        self._password = config.ADMIN_PASSWORD if password is None else password
        self._clock = clock
        self._lock = threading.Lock()
        self._sessions: dict[str, float] = {}       # ключ сеанса -> когда истекает
        self._failures = 0
        self._locked_until = 0.0

    def login(self, name: str, password: str) -> str:
        """Проверяет имя и пароль и возвращает ключ сеанса."""
        with self._lock:
            now = self._clock()
            if now < self._locked_until:
                wait = int(self._locked_until - now) + 1
                raise AdminError(f"слишком много попыток — подождите {wait} с")
            # проверяются оба, даже если имя уже не подошло: ответ не подсказывает, что именно неверно
            name_ok = _same((name or "").strip().lower(), self._name)
            password_ok = _same(password or "", self._password)
            if not self._password or not (name_ok and password_ok):
                self._failures += 1
                if self._failures >= config.ADMIN_ATTEMPTS:
                    self._failures = 0
                    self._locked_until = now + config.ADMIN_LOCK_SECONDS
                raise AdminError("неверное имя или пароль")
            self._failures = 0
            token = secrets.token_urlsafe(32)
            self._sessions[token] = now + config.ADMIN_SESSION_HOURS * 3600
            return token

    def check(self, token: str | None) -> bool:
        if not token:
            return False
        with self._lock:
            expires = self._sessions.get(token)
            if expires is None:
                return False
            if self._clock() > expires:
                del self._sessions[token]
                return False
            return True

    def logout(self, token: str | None) -> None:
        with self._lock:
            self._sessions.pop(token or "", None)
