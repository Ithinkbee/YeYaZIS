"""Викторина при взятии фигуры: определить язык слова, записанного латиницей.

Слова берутся из настоящего обучающего корпуса, а не из отдельного списка:
викторина должна опираться на те же данные, на которых обучены методы, иначе
она была бы просто украшением.

Отбор слов подчинён одному правилу: по записи латиницей язык должен быть
определим в принципе. Поэтому отбрасываются слова, транслитерация которых
совпала со словом другого языка, слишком короткие слова и слова, встреченные
в корпусе один раз (чаще всего это опечатки и имена собственные).
"""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass

from . import config, corpus, preprocess, translit

#: длина слова, пригодного для викторины
MIN_LENGTH = 5
MAX_LENGTH = 14

#: слово должно встретиться в корпусе хотя бы столько раз
MIN_FREQUENCY = 2

#: сколько слов держать в банке на каждый язык
BANK_SIZE = 400


@dataclass(slots=True, frozen=True)
class QuizWord:
    """Слово для викторины."""

    #: как слово выглядит в корпусе
    original: str
    #: как оно показывается игроку — латиницей
    shown: str
    #: язык-эталон
    language: str

    @property
    def language_name(self) -> str:
        return config.language_name(self.language)


class WordBank:
    """Банк слов для викторины, собранный по обучающему корпусу."""

    def __init__(self, words: dict[str, list[QuizWord]] | None = None) -> None:
        self.words: dict[str, list[QuizWord]] = words or {}

    @property
    def ready(self) -> bool:
        return all(self.words.get(code) for code in config.LANGUAGE_CODES)

    def size(self, code: str) -> int:
        return len(self.words.get(code, []))

    def pick(self, rng: random.Random | None = None, language: str | None = None) -> QuizWord | None:
        """Случайное слово; язык выбирается поровну, если не задан явно."""
        generator = rng or random
        if language is None:
            available = [code for code in config.LANGUAGE_CODES if self.words.get(code)]
            if not available:
                return None
            language = generator.choice(available)
        pool = self.words.get(language)
        return generator.choice(pool) if pool else None

    def find(self, shown: str) -> QuizWord | None:
        """Ищет слово по его латинской записи — для проверки ответа.

        Ответ проверяется на сервере: если бы эталон уходил в браузер вместе с
        вопросом, его можно было бы подсмотреть в исходном коде страницы.
        """
        shown = shown.strip().lower()
        for pool in self.words.values():
            for word in pool:
                if word.shown == shown:
                    return word
        return None


def _vocabulary(text: str) -> Counter[str]:
    """Частоты слов нормализованного текста."""
    return Counter(word for word in text.split() if MIN_LENGTH <= len(word) <= MAX_LENGTH)


def build_bank(training_corpus: dict[str, str] | None = None) -> WordBank:
    """Собирает банк слов по обучающему корпусу.

    Слово попадает в банк, только если его латинская запись не встречается
    среди слов другого языка: иначе вопрос не имел бы однозначного ответа.
    """
    if training_corpus is None:
        training_corpus = corpus.load_training_corpus()

    vocabularies = {code: _vocabulary(text) for code, text in training_corpus.items()}

    # латинские записи всех слов каждого языка — для проверки на столкновения
    latin_forms: dict[str, set[str]] = {
        code: {translit.latinize(word, code) for word in vocabulary}
        for code, vocabulary in vocabularies.items()
    }

    bank: dict[str, list[QuizWord]] = {}
    for code, vocabulary in vocabularies.items():
        others: set[str] = set()
        for other_code, forms in latin_forms.items():
            if other_code != code:
                others |= forms

        candidates: list[tuple[int, QuizWord]] = []
        for word, count in vocabulary.items():
            if count < MIN_FREQUENCY:
                continue
            shown = translit.latinize(word, code)
            if not translit.looks_latin(shown):
                continue
            if not MIN_LENGTH <= len(shown) <= MAX_LENGTH + 4:
                continue
            if shown in others:
                continue  # такое же слово есть в другом языке — вопрос нечестен
            candidates.append((count, QuizWord(original=word, shown=shown, language=code)))

        candidates.sort(key=lambda pair: (-pair[0], pair[1].shown))
        bank[code] = [word for _, word in candidates[:BANK_SIZE]]

    return WordBank(bank)


def system_opinion(recognizer, word: QuizWord) -> dict[str, str]:
    """Что ответили бы методы системы на ту же латинскую запись.

    Ответ показывается игроку после его собственного: профили русского языка
    построены по кириллице, поэтому на транслитерации методы ошибаются, и это
    наглядно объясняет границы алфавитного подхода.
    """
    if recognizer is None or not recognizer.trained:
        return {}
    opinions: dict[str, str] = {}
    for code, method in recognizer.methods.items():
        try:
            opinions[code] = method.classify(word.shown).language
        except RuntimeError:
            continue
    return opinions


def opinion_summary(opinions: dict[str, str], word: QuizWord) -> str:
    """Короткий вывод о том, справилась ли система с транслитерацией."""
    if not opinions:
        return ""
    correct = sum(1 for answer in opinions.values() if answer == word.language)
    total = len(opinions)
    if correct == total:
        return "Методы системы тоже не ошиблись."
    if correct == 0:
        return (
            "Все методы ошиблись: их профиль русского языка построен по "
            "кириллице, а латиница для них выглядит немецкой."
        )
    return f"Методы системы угадали {correct} из {total}."
