"""Стоп-слова (data/stopwords/<язык>.txt) и устойчивые служебные обороты."""

from __future__ import annotations

from functools import lru_cache

from izbornik import config

#: Служебные обороты, которые ведут себя как составной предлог или вводное
#: слово. Слова в них по отдельности значимы («очередь», «число», «счёт»),
#: но в обороте смысла не несут: «в свою очередь» — не об очереди, «в том
#: числе» — не о числе. Такие слова из расчёта весов исключаются так же, как
#: стоп-слова. Оборот задаётся словоформами в нижнем регистре, «ё» → «е».
STOP_PHRASES: dict[str, tuple[tuple[str, ...], ...]] = {
    "ru": tuple(
        tuple(phrase.split())
        for phrase in (
            "в том числе", "в свою очередь", "в первую очередь", "в целом", "в частности",
            "в рамках", "в качестве", "с помощью", "при помощи", "за счет", "на основе",
            "на основании", "в виде", "в результате", "в течение", "в случае", "в том случае",
            "на сегодняшний день", "в настоящее время", "с точки зрения", "по сравнению",
            "в связи", "в отличие", "в зависимости", "в соответствии", "в ходе", "по мнению",
            "таким образом", "тем самым", "к примеру", "на самом деле", "в конечном счете",
            "в конце концов", "до сих пор", "по отношению", "в пределах", "в сущности",
            "по крайней мере", "в том же", "в первую", "с одной стороны", "с другой стороны",
            "в то же время", "на данный момент", "в данном случае", "в итоге", "в общем",
        )
    ),
    "de": tuple(
        tuple(phrase.split())
        for phrase in (
            "zum beispiel", "im allgemeinen", "im rahmen", "mit hilfe", "im gegensatz",
            "in bezug", "im laufe", "im zusammenhang", "auf grund", "im folgenden",
            "in der regel", "im wesentlichen", "vor allem", "unter anderem", "im vergleich",
            "in form", "zum teil", "im grunde", "am ende", "im sinne", "in hinblick",
            "im hinblick", "mit ausnahme", "im fall", "im falle", "zum zeitpunkt",
        )
    ),
}


@lru_cache(maxsize=None)
def load(language: str) -> frozenset[str]:
    """Стоп-слова языка в нижнем регистре; «ё» приведена к «е»."""
    path = config.STOPWORDS_DIR / f"{language}.txt"
    words: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        words.add(line.lower().replace("ё", "е"))
    return frozenset(words)


def phrase_spans(words: list[str], language: str) -> set[int]:
    """Номера слов, входящих в служебные обороты."""
    lowered = [w.lower().replace("ё", "е") for w in words]
    covered: set[int] = set()
    for phrase in STOP_PHRASES.get(language, ()):
        size = len(phrase)
        for start in range(len(lowered) - size + 1):
            if tuple(lowered[start:start + size]) == phrase:
                covered.update(range(start, start + size))
    return covered
