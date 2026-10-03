"""Поле букв для боя с Пафнутием.

В поле спрятаны ключевые слова реферата одного документа коллекции: воины,
которых игрок выводит против паучат, — это слова, которые система сама сочла
главными в тексте. Каждое следующее поле берётся из реферата другого
документа.

Правила поля:

* слово читается по прямой — слева направо или сверху вниз;
* слова не пересекаются: найденное слово стирается с поля, и общая буква
  испортила бы соседнее слово;
* остальные клетки заполняются буквами с частотами языка, подсчитанными по
  текстам коллекции, — при равномерном заполнении слова выделялись бы среди
  частых «Ъ» и «Щ»;
* каждое слово читается в поле ровно один раз: если случайные буквы сложились
  в спрятанное слово ещё где-то, заполнение повторяется. Поэтому же в одно
  поле не попадают слова, одно из которых входит в другое.
"""

from __future__ import annotations

import random
import threading
from collections import Counter
from dataclasses import dataclass

from izbornik import config
from izbornik.collection import Collection
from izbornik.keywords import KeywordSummary

ALPHABETS = {
    "ru": "абвгдежзийклмнопрстуфхцчшщъыьэюя",
    "de": "abcdefghijklmnopqrstuvwxyzäöüß",
}

RIGHT = "right"
DOWN = "down"


def grid_letters(word: str) -> str:
    """Слово буквами поля: заглавными. «ß» заглавной становится «SS», поэтому
    для неё берётся заглавная «ẞ» — одна буква на клетку."""
    return "".join("ẞ" if ch == "ß" else ch.upper() for ch in word)


def eligible(word: str, language: str, max_length: int) -> bool:
    """Годится ли ключевое слово в воины."""
    if not config.BATTLE_WORD_MIN_LEN <= len(word) <= max_length:
        return False
    # дефис, пробел, цифры, чужой алфавит; «ё» pymorphy3 в леммах уже заменил на «е»
    if any(ch.lower() not in ALPHABETS[language] for ch in word):
        return False
    # аббревиатуры («БЗ», «KNN», «URIs») — не слова
    return sum(ch.isupper() for ch in word) <= 1


@dataclass
class BankWord:
    text: str        # как показывать в списке: «Онегин»
    letters: str     # как в поле: «ОНЕГИН»
    rank: int        # место ключевого слова в реферате (1 — самое значимое)


@dataclass
class Placement:
    text: str
    letters: str
    row: int
    col: int
    direction: str   # right | down
    rank: int = 0

    @property
    def cells(self) -> list[tuple[int, int]]:
        dr, dc = (0, 1) if self.direction == RIGHT else (1, 0)
        return [(self.row + dr * i, self.col + dc * i) for i in range(len(self.letters))]

    def to_dict(self) -> dict:
        return {"text": self.text, "letters": self.letters, "row": self.row, "col": self.col,
                "dir": self.direction, "rank": self.rank}


@dataclass
class Grid:
    doc_id: str
    title: str
    language: str
    rows: int
    cols: int
    letters: list[list[str]]
    words: list[Placement]

    def lines(self) -> list[str]:
        """Строки поля слева направо и столбцы сверху вниз — всё, что можно прочитать."""
        rows = ["".join(row) for row in self.letters]
        columns = ["".join(self.letters[r][c] for r in range(self.rows)) for c in range(self.cols)]
        return rows + columns

    def occurrences(self, letters: str) -> int:
        """Сколько раз слово читается в поле."""
        return sum(_count(line, letters) for line in self.lines())

    def to_dict(self) -> dict:
        return {
            "doc_id": self.doc_id,
            "title": self.title,
            "language": self.language,
            "rows": self.rows,
            "cols": self.cols,
            "letters": ["".join(row) for row in self.letters],
            "words": [p.to_dict() for p in self.words],
            "link": f"/doc/{self.doc_id}" if self.doc_id else "",
        }


def _count(line: str, word: str) -> int:
    """Вхождения с перекрытием: «ААА» содержит «АА» дважды."""
    return sum(1 for i in range(len(line) - len(word) + 1) if line.startswith(word, i))


# --- слова из реферата ------------------------------------------------------------------

def keyword_words(keywords: KeywordSummary, language: str, max_length: int) -> list[BankWord]:
    """Ключевые слова реферата, годные в воины, в порядке значимости.

    Берутся слова верхнего уровня и немецкие сложные слова под ними
    («Räuberbande» под «Räuber»); русские именные группы — словосочетания, в
    поле по прямой они не укладываются.
    """
    words: list[BankWord] = []
    seen: set[str] = set()
    for rank, top in enumerate(keywords.tree, start=1):
        for _, keyword in top.walk():
            if keyword.kind == "phrase" or not eligible(keyword.text, language, max_length):
                continue
            letters = grid_letters(keyword.text)
            if letters not in seen:
                seen.add(letters)
                words.append(BankWord(keyword.text, letters, rank))
    return words


def choose_words(pool: list[BankWord], count: int, rng: random.Random) -> list[BankWord]:
    """Случайные слова из запаса; слово, входящее в другое, не берётся."""
    shuffled = pool[:]
    rng.shuffle(shuffled)
    chosen: list[BankWord] = []
    for word in shuffled:
        if any(word.letters in other.letters or other.letters in word.letters for other in chosen):
            continue
        chosen.append(word)
        if len(chosen) == count:
            break
    return chosen


# --- раскладка --------------------------------------------------------------------------

def place(words: list[BankWord], rows: int, cols: int, rng: random.Random,
          attempts: int = 60) -> list[Placement] | None:
    """Раскладывает слова без пересечений; None — если места не нашлось.

    Длинные слова раскладываются первыми: им труднее найти место. Направление
    выбирается равновероятно из возможных — иначе горизонтальных слов было бы
    заметно больше, ведь строка длиннее столбца.
    """
    order = sorted(words, key=lambda w: -len(w.letters))
    for _ in range(attempts):
        taken: set[tuple[int, int]] = set()
        placed: list[Placement] = []
        for word in order:
            options: dict[str, list[Placement]] = {RIGHT: [], DOWN: []}
            size = len(word.letters)
            for direction in (RIGHT, DOWN):
                last_row = rows - (size if direction == DOWN else 1)
                last_col = cols - (size if direction == RIGHT else 1)
                for row in range(last_row + 1):
                    for col in range(last_col + 1):
                        candidate = Placement(word.text, word.letters, row, col, direction, word.rank)
                        if taken.isdisjoint(candidate.cells):
                            options[direction].append(candidate)
            directions = [d for d in (RIGHT, DOWN) if options[d]]
            if not directions:
                break
            choice = rng.choice(options[rng.choice(directions)])
            taken.update(choice.cells)
            placed.append(choice)
        else:
            return placed
    return None


def make_grid(words: list[BankWord], language: str, frequencies: dict[str, float], rng: random.Random,
              rows: int = config.BATTLE_GRID_ROWS, cols: int = config.BATTLE_GRID_COLS,
              doc_id: str = "", title: str = "") -> Grid:
    """Поле с разложенными словами и заполненными клетками."""
    placements = place(words, rows, cols, rng)
    if placements is None:
        raise ValueError("слова не помещаются в поле")
    letters, weights = zip(*sorted(frequencies.items()))
    for _ in range(50):
        cells = [[""] * cols for _ in range(rows)]
        for placement in placements:
            for (row, col), letter in zip(placement.cells, placement.letters):
                cells[row][col] = letter
        for row in cells:
            for col, value in enumerate(row):
                if not value:
                    row[col] = rng.choices(letters, weights)[0]
        grid = Grid(doc_id, title, language, rows, cols, cells, placements)
        if all(grid.occurrences(p.letters) == 1 for p in placements):
            return grid
    raise ValueError("не удалось заполнить поле так, чтобы слова не повторялись")


class WordBank:
    """Слова для полей боя: ключевые слова рефератов документов коллекции.

    Реферат документа строится при первом обращении к нему и запоминается
    вместе со словами; частоты букв считаются по текстам коллекции один раз
    на язык.
    """

    def __init__(self, collection: Collection) -> None:
        self.collection = collection
        self._words: dict[str, list[BankWord]] = {}
        self._frequencies: dict[str, dict[str, float]] = {}
        self._lock = threading.Lock()

    @staticmethod
    def max_length() -> int:
        return max(config.BATTLE_GRID_ROWS, config.BATTLE_GRID_COLS)

    def words(self, doc_id: str) -> list[BankWord]:
        with self._lock:
            if doc_id not in self._words:
                entry = self.collection.get(doc_id)
                if entry is None:
                    raise KeyError(doc_id)
                keywords = self.collection.summarize(doc_id).summary.keywords
                self._words[doc_id] = keyword_words(keywords, entry.language, self.max_length())
            return self._words[doc_id]

    def frequencies(self, language: str) -> dict[str, float]:
        """Доли букв в текстах коллекции на этом языке (в заглавном виде)."""
        with self._lock:
            if language not in self._frequencies:
                alphabet = ALPHABETS[language]
                counts: Counter = Counter()
                for entry in self.collection.by_language(language):
                    text = self.collection.text(entry.id).lower().replace("ё", "е")
                    counts.update(ch for ch in text if ch in alphabet)
                total = sum(counts.values()) or 1
                self._frequencies[language] = {grid_letters(ch): n / total for ch, n in counts.items()}
            return self._frequencies[language]

    def grid(self, language: str, rng: random.Random | None = None, exclude=()) -> Grid:
        """Новое поле из реферата случайного документа, которого нет в exclude."""
        rng = rng or random.Random()
        entries = self.collection.by_language(language)
        if not entries:
            raise LookupError(f"в коллекции нет документов на языке «{language}»")
        excluded = set(exclude)
        order = [e for e in entries if e.id not in excluded]
        rng.shuffle(order)
        order += [e for e in entries if e.id in excluded]     # все сыграны — идём по второму кругу
        low, high = config.BATTLE_WORDS
        for entry in order:
            chosen = choose_words(self.words(entry.id), rng.randint(low, high), rng)
            if len(chosen) < low:
                continue
            try:
                return make_grid(chosen, language, self.frequencies(language), rng,
                                 doc_id=entry.id, title=entry.title)
            except ValueError:
                continue
        raise LookupError("в коллекции нет документа с подходящими ключевыми словами")
