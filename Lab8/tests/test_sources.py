"""Откуда берётся текст: файлы, страницы, статьи, буфер обмена и горячие клавиши."""

from __future__ import annotations

import io
import sys
import time
import zipfile

import pytest

from glashatai import desktop
from glashatai.articles import Collection
from glashatai.text.extract import ExtractError, from_docx, from_file, from_html, from_url, tidy_text


def test_html_keeps_only_the_article():
    html = ("<html><head><title>Compiler – Wiki</title><script>var x = 1;</script></head><body>"
            "<nav>Menü Start Suche</nav><main><h1>Compiler</h1><p>Ein <b>Compiler</b> übersetzt.<sup>[1]</sup></p>"
            "<div hidden>versteckt</div><div style='display: none'>auch versteckt</div>"
            "<p>" + "Zweiter Absatz. " * 40 + "</p></main><footer>Impressum</footer></body></html>")
    title, text = from_html(html)
    assert title == "Compiler – Wiki"
    assert text.startswith("# Compiler\n\nEin Compiler übersetzt.")
    for hidden in ("Menü", "var x", "versteckt", "Impressum", "[1]"):
        assert hidden not in text


def test_hyphenation_and_spaces_are_repaired():
    assert tidy_text("Der Über-\nsetzer  liest­ den\xa0Text.\n\n\n\nNeu") == "Der Übersetzer liest den Text.\n\nNeu"


def make_docx(paragraphs: list[tuple[str, bool]]) -> bytes:
    body = "".join(
        f'<w:p>{"<w:pPr><w:pStyle w:val=\"Heading1\"/></w:pPr>" if heading else ""}<w:r><w:t>{text}</w:t></w:r></w:p>'
        for text, heading in paragraphs)
    xml = f'<?xml version="1.0"?><w:document xmlns:w="w"><w:body>{body}</w:body></w:document>'
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as packed:
        packed.writestr("word/document.xml", xml)
    return buffer.getvalue()


def test_docx():
    data = make_docx([("Einleitung", True), ("Der Compiler übersetzt &amp; prüft.", False)])
    assert from_docx(data) == "# Einleitung\n\nDer Compiler übersetzt & prüft."
    with pytest.raises(ExtractError):
        from_docx(b"not a zip")


def make_pdf(text: str) -> bytes:
    """Минимальный PDF с текстовым слоем (шрифт Helvetica, латиница)."""
    stream = f"BT /F1 12 Tf 72 720 Td ({text}) Tj ET".encode("latin-1")
    objects = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(out.tell())
        out.write(f"{number} 0 obj\n".encode() + body + b"\nendobj\n")
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for offset in offsets:
        out.write(f"{offset:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF".encode())
    return out.getvalue()


def test_pdf():
    pytest.importorskip("pypdf")
    title, text = from_file("artikel.pdf", make_pdf("Ein Compiler uebersetzt Programme."))
    assert title == "artikel" and "Compiler uebersetzt Programme" in text


def test_files_by_type():
    assert from_file("notiz.txt", "Hallo Welt".encode("cp1252"))[1] == "Hallo Welt"
    assert from_file("text.md", b"## Titel\n\n**Fett** und [Link](http://x)")[1] == "# Titel\n\nFett und Link"
    title, text = from_file("seite.html", "<html><title>T</title><p>Ä Ö Ü</p></html>".encode("utf-8"))
    assert title == "T" and text == "Ä Ö Ü"


def test_bad_url():
    with pytest.raises(ExtractError):
        from_url("ftp://example.org/datei")
    with pytest.raises(ExtractError):
        from_url("keine adresse")


def test_articles():
    collection = Collection()
    assert len(collection) == 5
    ids = [a.id for a in collection]
    assert ids[0] == "de-cs-compiler" and "de-cs-semweb" in ids
    article = collection.get("de-cs-nn")
    summary = article.summary()
    assert summary["title"] == "Künstliches neuronales Netz" and summary["words"] > 2000
    assert summary["source"]["license"] == "CC BY-SA 4.0" and article.sections
    assert collection.get("nope") is None


def test_hotkey_parsing():
    assert desktop.parse_hotkey("Ctrl+Alt+R") == (desktop.MOD_CONTROL | desktop.MOD_ALT | desktop.MOD_NOREPEAT, ord("R"))
    assert desktop.parse_hotkey("Shift + F9")[1] == 0x78
    with pytest.raises(ValueError):
        desktop.parse_hotkey("Ctrl+Alt")


windows = pytest.mark.skipif(sys.platform != "win32", reason="буфер обмена и горячие клавиши — только Windows")


@pytest.fixture()
def clipboard():
    """Буфер обмена пользователя после теста возвращается на место."""
    saved = desktop.read_clipboard()
    yield
    if saved is not None:
        desktop.write_clipboard(saved)


@windows
def test_clipboard_roundtrip(clipboard):
    before = desktop.sequence()
    assert desktop.write_clipboard("Größe: 12 GB — z. B.")
    assert desktop.read_clipboard() == "Größe: 12 GB — z. B."
    assert desktop.sequence() != before


@windows
def test_clipboard_watcher_reads_only_new_text(clipboard):
    got = []
    watcher = desktop.Desktop(lambda text, source: got.append((source, text)), lambda: None)
    desktop.write_clipboard("Alter Text vor dem Einschalten.")
    watcher.set_clipboard(True)
    time.sleep(0.5)
    desktop.write_clipboard("Neuer Text aus Word.")
    deadline = time.time() + 3
    while not got and time.time() < deadline:
        time.sleep(0.05)
    watcher.set_clipboard(False)
    desktop.write_clipboard("Nach dem Ausschalten.")
    time.sleep(0.6)
    watcher.close()
    assert got == [("clipboard", "Neuer Text aus Word.")]
    assert watcher.state.events[-1]["kind"] == "clipboard"


@windows
def test_hotkeys_register_and_release():
    watcher = desktop.Desktop(lambda text, source: None, lambda: None)
    watcher.set_hotkeys(True)
    if not watcher.state.hotkeys:
        pytest.skip(f"сочетание занято: {watcher.state.problem}")
    # повторная регистрация того же сочетания другой копией не удаётся — оно наше
    second = desktop.Desktop(lambda text, source: None, lambda: None)
    second.set_hotkeys(True)
    assert not second.state.hotkeys and "занято" in second.state.problem
    watcher.set_hotkeys(False)
    assert not watcher.state.hotkeys
    second.close()
    watcher.close()
