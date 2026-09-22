"""Обучающий корпус и тестовая коллекция.

Обучающий корпус лежит в `data/train/<код языка>/*.txt` — это обычные
текстовые файлы; методичка требует от 20 до 120 Кб на язык.

Тестовая коллекция — HTML-документы в `data/collection`, её эталонная
разметка хранится в `data/labels.csv` двумя колонками: имя файла и код языка.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path

from . import config, preprocess
from .models import Document


@dataclass(slots=True)
class CorpusStats:
    """Объём обучающего корпуса одного языка."""

    code: str
    files: int
    bytes: int
    letters: int
    words: int

    @property
    def kilobytes(self) -> float:
        return self.bytes / 1024

    @property
    def within_limits(self) -> bool:
        """Укладывается ли объём в требование методички (20–120 Кб)."""
        return config.TRAIN_MIN_BYTES <= self.bytes <= config.TRAIN_MAX_BYTES

    @property
    def verdict(self) -> str:
        if self.bytes < config.TRAIN_MIN_BYTES:
            return "мало"
        if self.bytes > config.TRAIN_MAX_BYTES:
            return "много"
        return "в норме"


# --- Обучающий корпус -------------------------------------------------------


def train_files(code: str) -> list[Path]:
    """Файлы обучающего корпуса одного языка, в устойчивом порядке."""
    directory = config.TRAIN_DIR / code
    if not directory.exists():
        return []
    return sorted(path for path in directory.glob("*.txt") if path.is_file())


def load_training_corpus() -> dict[str, str]:
    """Читает обучающий корпус и возвращает нормализованный текст по языкам.

    Нормализация выполняется один раз здесь, а не в каждом методе: все три
    метода работают с одним и тем же представлением текста, иначе сравнение
    их качества было бы некорректным.
    """
    corpus: dict[str, str] = {}
    for code in config.LANGUAGE_CODES:
        pieces = [
            path.read_text(encoding="utf-8", errors="replace") for path in train_files(code)
        ]
        if not pieces:
            continue
        corpus[code] = preprocess.normalize("\n".join(pieces))
    missing = [code for code in config.LANGUAGE_CODES if code not in corpus]
    if missing:
        names = ", ".join(config.language_name(code) for code in missing)
        raise FileNotFoundError(
            f"обучающий корпус пуст для языков: {names}. "
            f"Положите тексты в {config.TRAIN_DIR} или выполните "
            f"python tools/build_corpus.py"
        )
    return corpus


def corpus_stats() -> dict[str, CorpusStats]:
    """Объём корпуса по языкам — для проверки требований методички."""
    stats: dict[str, CorpusStats] = {}
    for code in config.LANGUAGE_CODES:
        files = train_files(code)
        size = sum(path.stat().st_size for path in files)
        text = preprocess.normalize(
            "\n".join(path.read_text(encoding="utf-8", errors="replace") for path in files)
        )
        stats[code] = CorpusStats(
            code=code,
            files=len(files),
            bytes=size,
            letters=preprocess.count_letters(text),
            words=len(text.split()),
        )
    return stats


# --- Эталонная разметка -----------------------------------------------------


def load_labels() -> dict[str, str]:
    """Читает `data/labels.csv`: имя файла -> код языка."""
    if not config.LABELS_PATH.exists():
        return {}
    labels: dict[str, str] = {}
    with config.LABELS_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            name = (row.get("file") or "").strip()
            code = (row.get("language") or "").strip()
            if name and code:
                labels[name] = code
    return labels


def save_labels(labels: dict[str, str]) -> None:
    """Сохраняет эталонную разметку тестовой коллекции."""
    config.LABELS_PATH.parent.mkdir(parents=True, exist_ok=True)
    with config.LABELS_PATH.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["file", "language"])
        for name in sorted(labels):
            writer.writerow([name, labels[name]])


# --- Тестовая коллекция -----------------------------------------------------


def collection_files() -> list[Path]:
    """HTML-документы тестовой коллекции в алфавитном порядке."""
    if not config.COLLECTION_DIR.exists():
        return []
    return sorted(
        path
        for path in config.COLLECTION_DIR.iterdir()
        if path.is_file() and path.suffix.lower() in config.COLLECTION_EXTENSIONS
    )


def load_document(path: Path, labels: dict[str, str] | None = None) -> Document:
    """Читает один документ коллекции и выполняет шаг 1 алгоритма."""
    if labels is None:
        labels = load_labels()
    title, _, normalized = preprocess.read_html(path)
    return Document(
        doc_id=path.name,
        title=title,
        path=path,
        text=normalized,
        letters=preprocess.count_letters(normalized),
        words=len(normalized.split()),
        size=path.stat().st_size,
        gold=labels.get(path.name),
    )


def load_collection() -> list[Document]:
    """Читает всю тестовую коллекцию."""
    labels = load_labels()
    return [load_document(path, labels) for path in collection_files()]


def document_from_text(source: str, *, title: str = "Введённый текст", is_html: bool = False) -> Document:
    """Готовит документ из текста, введённого пользователем или загруженного.

    Используется формой «проверить свой текст»: файла на диске нет, поэтому
    `path` остаётся пустым, а идентификатор документа — служебный.
    """
    if is_html:
        title = preprocess.extract_title(source, fallback=title)
    _, normalized = preprocess.prepare_text(source, is_html=is_html)
    return Document(
        doc_id="—",
        title=title,
        path=None,
        text=normalized,
        letters=preprocess.count_letters(normalized),
        words=len(normalized.split()),
        size=len(source.encode("utf-8")),
        gold=None,
    )
