"""Морфологический анализ русского текста.

Отвечает за приведение текста и запроса к единому виду — множеству лемм,
которые и выступают терминами поискового образа документа (ПОД) и запроса (ПОЗ).
"""

from __future__ import annotations

import re
from collections import Counter
from functools import lru_cache
from typing import Iterable

from .. import config

#: слова русские/латинские и числа, допускается дефис внутри слова
TOKEN_RE = re.compile(r"[а-яёa-z0-9]+(?:-[а-яёa-z0-9]+)*", re.IGNORECASE)

MIN_TOKEN_LENGTH = 2

_FALLBACK_STOPWORDS = {
    "и", "в", "во", "не", "что", "он", "на", "я", "с", "со", "как", "а", "то",
    "все", "она", "так", "его", "но", "да", "ты", "к", "у", "же", "вы", "за",
    "бы", "по", "только", "ее", "мне", "было", "вот", "от", "меня", "еще",
    "нет", "о", "из", "ему", "теперь", "когда", "даже", "ну", "вдруг", "ли",
    "если", "уже", "или", "ни", "быть", "был", "него", "до", "вас", "нибудь",
    "опять", "уж", "вам", "ведь", "там", "потом", "себя", "ничего", "ей",
    "может", "они", "тут", "где", "есть", "надо", "ней", "для", "мы", "тебя",
    "их", "чем", "была", "сам", "чтоб", "без", "будто", "чего", "раз", "тоже",
    "себе", "под", "будет", "ж", "тогда", "кто", "этот", "того", "потому",
    "этого", "какой", "совсем", "ним", "здесь", "этом", "один", "почти",
    "мой", "тем", "чтобы", "нее", "сейчас", "были", "куда", "зачем", "всех",
    "никогда", "можно", "при", "наконец", "два", "об", "другой", "хоть",
    "после", "над", "больше", "тот", "через", "эти", "нас", "про", "всего",
    "них", "какая", "много", "разве", "три", "эту", "моя", "впрочем",
    "хорошо", "свою", "этой", "перед", "иногда", "лучше", "чуть", "том",
    "нельзя", "такой", "им", "более", "всегда", "конечно", "всю", "между",
}


def _load_stopwords() -> set[str]:
    """Загружает стоп-слова из data/stopwords_ru.txt, иначе берёт встроенный список."""
    path = config.STOPWORDS_PATH
    if path.exists():
        words = set()
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip().lower()
            if line and not line.startswith("#"):
                words.add(line)
        if words:
            return words
    return set(_FALLBACK_STOPWORDS)


STOPWORDS = _load_stopwords()

_morph = None


def get_morph():
    """Ленивая инициализация анализатора pymorphy3 (загрузка словарей ~1 c)."""
    global _morph
    if _morph is None:
        import pymorphy3

        _morph = pymorphy3.MorphAnalyzer()
    return _morph


def tokenize(text: str) -> list[str]:
    """Разбивает текст на токены в нижнем регистре."""
    return [t.lower().replace("ё", "е") for t in TOKEN_RE.findall(text or "")]


def is_stopword(word: str) -> bool:
    return word in STOPWORDS


def is_significant(token: str) -> bool:
    """Значимый ли токен: достаточной длины, не стоп-слово, не голое число."""
    if len(token) < MIN_TOKEN_LENGTH:
        return False
    if is_stopword(token):
        return False
    if token.isdigit():
        return False
    return True


@lru_cache(maxsize=200_000)
def lemma(word: str) -> str:
    """Нормальная форма слова. Кэш существенно ускоряет индексацию."""
    if not word:
        return word
    if not re.search(r"[а-яё]", word):
        # латиница/цифры морфологии не требуют
        return word
    try:
        parsed = get_morph().parse(word)
    except Exception:  # словарь недоступен — работаем без лемматизации
        return word
    if not parsed:
        return word
    return parsed[0].normal_form.replace("ё", "е")


@lru_cache(maxsize=100_000)
def parse_word(word: str) -> dict:
    """Морфологическая справка о слове — показывается пользователю в интерфейсе."""
    info = {
        "word": word,
        "lemma": word,
        "pos": "",
        "pos_ru": "",
        "grammemes": "",
        "score": 0.0,
        "is_stopword": is_stopword(word),
    }
    if not re.search(r"[а-яё]", word):
        info["pos_ru"] = "латиница/число"
        return info
    try:
        parsed = get_morph().parse(word)
    except Exception:
        return info
    if not parsed:
        return info
    best = parsed[0]
    pos = str(best.tag.POS or "")
    info.update(
        lemma=best.normal_form.replace("ё", "е"),
        pos=pos,
        pos_ru=POS_NAMES.get(pos, pos or "неизв."),
        grammemes=str(best.tag),
        score=round(float(best.score), 3),
    )
    return info


POS_NAMES = {
    "NOUN": "существительное",
    "ADJF": "прилагательное",
    "ADJS": "кр. прилагательное",
    "COMP": "компаратив",
    "VERB": "глагол",
    "INFN": "инфинитив",
    "PRTF": "причастие",
    "PRTS": "кр. причастие",
    "GRND": "деепричастие",
    "NUMR": "числительное",
    "ADVB": "наречие",
    "NPRO": "местоимение",
    "PRED": "предикатив",
    "PREP": "предлог",
    "CONJ": "союз",
    "PRCL": "частица",
    "INTJ": "междометие",
}


def lemmatize(tokens: Iterable[str]) -> list[tuple[str, str]]:
    """Пары (словоформа, лемма) для значимых токенов."""
    return [(t, lemma(t)) for t in tokens if is_significant(t)]


def analyze_text(text: str, use_lemmas: bool = True) -> tuple[Counter, dict[str, Counter]]:
    """Поисковый образ документа.

    Возвращает:
        counts — частоты терминов Q_ij в документе;
        forms  — для каждого термина частоты встретившихся словоформ
                 (нужны для автодополнения и подсветки).

    При use_lemmas=False терминами становятся сами словоформы — этот режим
    нужен, чтобы экспериментально показать вклад морфологии в качество поиска.
    """
    counts: Counter = Counter()
    forms: dict[str, Counter] = {}
    for token, norm in lemmatize(tokenize(text)):
        term = norm if use_lemmas else token
        counts[term] += 1
        forms.setdefault(term, Counter())[token] += 1
    return counts, forms


def query_lemmas(query: str) -> list[str]:
    """Леммы запроса без повторов, порядок сохраняется."""
    seen: list[str] = []
    for _, norm in lemmatize(tokenize(query)):
        if norm not in seen:
            seen.append(norm)
    return seen
