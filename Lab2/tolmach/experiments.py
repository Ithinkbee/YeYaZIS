"""Исследование устойчивости методов к длине входного текста.

На полных документах тестовой коллекции все три метода дают одинаковый
результат: русский и немецкий пользуются разными системами письма, и задача
для страницы текста оказывается слишком простой, чтобы различить методы по
точности. Сравнивать их в таких условиях можно только по быстродействию.

Содержательное различие проявляется на коротких фрагментах. Поэтому каждый
документ режется на окна заданной длины, и точность измеряется отдельно для
каждой длины. Получается кривая «точность — длина входа», по которой видно,
сколько символов нужно методу, чтобы принять уверенное решение.

Нарезка идёт по границам слов: обрывать текст посреди слова значило бы
добавлять к задаче искусственную трудность, которой в реальных документах
нет.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import config
from .models import Document
from .recognizer import Recognizer

#: длины фрагментов в символах, на которых измеряется точность.
#:
#: Нижняя граница выбрана намеренно малой: на странице текста русско-немецкая
#: пара различается безошибочно всеми методами, и различия между ними видны
#: только там, где входа заведомо не хватает — на одном-двух словах.
LENGTHS: tuple[int, ...] = (10, 20, 40, 80, 150, 300, 600, 1200)

#: сколько непересекающихся окон брать из одного документа
WINDOWS_PER_DOCUMENT = 5


@dataclass(slots=True)
class LengthPoint:
    """Точка кривой «точность — длина» для одного метода."""

    method: str
    length: int
    correct: int
    total: int
    elapsed_ms: float

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 0.0

    @property
    def mean_ms(self) -> float:
        return self.elapsed_ms / self.total if self.total else 0.0


@dataclass(slots=True)
class LengthStudy:
    """Результат исследования по всем методам и длинам."""

    lengths: tuple[int, ...]
    #: метод -> длина -> точка
    points: dict[str, dict[int, LengthPoint]] = field(default_factory=dict)
    #: сколько фрагментов испытано на каждой длине
    samples: dict[int, int] = field(default_factory=dict)

    def curve(self, method: str) -> list[tuple[int, float]]:
        """Кривая точности метода: пары (длина, точность)."""
        row = self.points.get(method, {})
        return [(length, row[length].accuracy) for length in self.lengths if length in row]

    def threshold(self, method: str, target: float = 0.95) -> int | None:
        """Наименьшая длина, с которой метод устойчиво держит заданную точность.

        Устойчиво — значит, что на этой длине и на всех больших точность не
        опускается ниже порога. Одиночный удачный результат на коротком
        фрагменте порогом не считается.
        """
        row = self.points.get(method, {})
        ordered = [length for length in self.lengths if length in row]
        for position, length in enumerate(ordered):
            if all(row[rest].accuracy >= target for rest in ordered[position:]):
                return length
        return None

    def best_at(self, length: int) -> str | None:
        """Метод с наибольшей точностью на заданной длине."""
        candidates = {
            method: row[length].accuracy
            for method, row in self.points.items()
            if length in row
        }
        return max(candidates, key=candidates.get) if candidates else None


def windows(text: str, length: int, count: int = WINDOWS_PER_DOCUMENT) -> list[str]:
    """Нарезает текст на непересекающиеся окна примерно заданной длины.

    Граница окна сдвигается до ближайшего пробела, поэтому фактическая длина
    немного отличается от запрошенной — это честнее, чем обрывать слово.
    """
    if not text:
        return []
    pieces: list[str] = []
    start = 0
    while len(pieces) < count and start < len(text):
        end = min(start + length, len(text))
        if end < len(text):
            space = text.rfind(" ", start, end)
            if space > start:
                end = space
        piece = text[start:end].strip()
        if len(piece) < length * 0.5:
            break
        pieces.append(piece)
        start = end + 1
    return pieces


def run_length_study(
    recognizer: Recognizer,
    documents: list[Document],
    lengths: tuple[int, ...] = LENGTHS,
    windows_per_document: int = WINDOWS_PER_DOCUMENT,
) -> LengthStudy:
    """Измеряет точность каждого метода на фрагментах разной длины.

    Учитываются только размеченные документы: без эталона точность посчитать
    нельзя.
    """
    labelled = [document for document in documents if document.gold is not None]
    study = LengthStudy(lengths=lengths)
    for method_code in recognizer.methods:
        study.points[method_code] = {}

    for length in lengths:
        samples = 0
        totals: dict[str, LengthPoint] = {
            code: LengthPoint(method=code, length=length, correct=0, total=0, elapsed_ms=0.0)
            for code in recognizer.methods
        }
        for document in labelled:
            for piece in windows(document.text, length, windows_per_document):
                samples += 1
                for code, method in recognizer.methods.items():
                    result = method.classify(piece)
                    point = totals[code]
                    point.total += 1
                    point.elapsed_ms += result.elapsed_ms
                    if result.language == document.gold:
                        point.correct += 1
        study.samples[length] = samples
        for code, point in totals.items():
            study.points[code][length] = point

    return study


def summary_table(study: LengthStudy) -> list[dict[str, object]]:
    """Таблица «метод × длина» для интерфейса и отчёта."""
    rows: list[dict[str, object]] = []
    for method, row in study.points.items():
        rows.append(
            {
                "method": method,
                "accuracy": {length: row[length].accuracy for length in study.lengths if length in row},
                "mean_ms": {length: row[length].mean_ms for length in study.lengths if length in row},
                "threshold": study.threshold(method),
            }
        )
    return rows


def summary_lines(study: LengthStudy) -> list[str]:
    """Короткий словесный вывод исследования."""
    # число фрагментов зависит от длины: из документа выходит тем меньше окон,
    # чем они длиннее, поэтому указывается диапазон, а не одно значение
    counts = [study.samples[length] for length in study.lengths if length in study.samples]
    span = f"{min(counts)}–{max(counts)}" if counts and min(counts) != max(counts) else str(counts[0] if counts else 0)
    lines = [f"Точность на фрагментах разной длины (по {span} фрагментам на длину):"]
    for method, row in study.points.items():
        parts = ", ".join(
            f"{length} симв. — {row[length].accuracy:.0%}"
            for length in study.lengths
            if length in row
        )
        lines.append(f"  {method}: {parts}")
    for method in study.points:
        threshold = study.threshold(method)
        lines.append(
            f"  {method}: устойчивые 95% начинаются с "
            + (f"{threshold} символов" if threshold else "длины за пределами опыта")
        )
    return lines


#: доли немецкого текста в смеси; сетка сгущается у середины, где и проходит
#: граница решения — вдали от неё все методы отвечают одинаково
MIXTURE_RATIOS: tuple[float, ...] = (
    0.0, 0.1, 0.2, 0.3, 0.4, 0.45, 0.475, 0.5, 0.525, 0.55, 0.6, 0.7, 0.8, 0.9, 1.0
)


@dataclass(slots=True)
class MixtureStudy:
    """Поведение методов на документах, составленных из двух языков сразу.

    Реальная веб-страница нередко содержит текст на двух языках: цитату,
    меню, подпись. Опыт показывает, при какой доле второго языка метод меняет
    решение, то есть где именно проходит его граница.
    """

    ratios: tuple[float, ...]
    #: метод -> доля смесей, отнесённых к немецкому, по каждой доле смешивания
    shares: dict[str, dict[float, float]] = field(default_factory=dict)
    #: сколько смесей испытано на каждой доле
    samples: int = 0

    def crossover(self, method: str) -> float | None:
        """Доля немецкого, начиная с которой метод устойчиво отвечает «немецкий»."""
        row = self.shares.get(method, {})
        ordered = [ratio for ratio in self.ratios if ratio in row]
        for position, ratio in enumerate(ordered):
            if all(row[rest] >= 0.5 for rest in ordered[position:]):
                return ratio
        return None

    def balanced(self, method: str) -> float | None:
        """Ответ метода ровно на равной смеси — наиболее спорный случай."""
        return self.shares.get(method, {}).get(0.5)


def mix(first: str, second: str, ratio: float) -> str:
    """Склеивает два текста в заданной пропорции, сохраняя общую длину.

    Смешивание идёт крупными кусками, а не вперемешку по словам: так смесь
    похожа на настоящую страницу с разделом на другом языке, а не на
    бессвязный набор слов.
    """
    length = min(len(first), len(second))
    if not length:
        return (first or second).strip()
    head = first[: int(length * (1.0 - ratio))]
    tail = second[: int(length * ratio)]
    return f"{head} {tail}".strip()


def run_mixture_study(
    recognizer: Recognizer,
    documents: list[Document],
    ratios: tuple[float, ...] = MIXTURE_RATIOS,
) -> MixtureStudy:
    """Строит кривую «доля второго языка — решение метода».

    Русские документы смешиваются с немецкими попарно; для каждой доли
    считается, какая часть смесей отнесена к немецкому языку.
    """
    russian = [document for document in documents if document.gold == "ru"]
    german = [document for document in documents if document.gold == "de"]
    pairs = list(zip(russian, german))

    study = MixtureStudy(ratios=ratios, samples=len(pairs))
    for code in recognizer.methods:
        study.shares[code] = {}

    for ratio in ratios:
        texts = [mix(first.text, second.text, ratio) for first, second in pairs]
        for code, method in recognizer.methods.items():
            votes = sum(1 for text in texts if method.classify(text).language == "de")
            study.shares[code][ratio] = votes / len(texts) if texts else 0.0

    return study


def mixture_lines(study: MixtureStudy) -> list[str]:
    """Словесный вывод опыта со смешанным текстом."""
    lines = [f"Смешанный текст ({study.samples} пар документов):"]
    for method in study.shares:
        crossover = study.crossover(method)
        balanced = study.balanced(method)
        lines.append(
            f"  {method}: перелом при доле немецкого "
            + (f"{crossover:.1%}" if crossover is not None else "не достигнут")
            + (f", на равной смеси «немецкий» у {balanced:.0%} документов" if balanced is not None else "")
        )
    return lines


def language_confidence(recognizer: Recognizer, documents: list[Document]) -> dict[str, float]:
    """Средняя уверенность каждого метода по коллекции.

    Служит дополнением к точности: два метода могут одинаково угадывать язык,
    но с разным отрывом от второго варианта, а отрыв показывает, насколько
    решение устойчиво к шуму во входном тексте.
    """
    totals: dict[str, float] = {code: 0.0 for code in recognizer.methods}
    for document in documents:
        for code, method in recognizer.methods.items():
            totals[code] += method.classify(document.text).confidence
    count = len(documents) or 1
    return {code: value / count for code, value in totals.items()}


def alphabet_overlap() -> dict[str, object]:
    """Пересечение алфавитов языков варианта — справка для отчёта.

    Для русско-немецкой пары пересечение пусто, и это объясняет, почему
    алфавитный метод справляется с задачей не хуже более сложных.
    """
    return {
        "languages": [config.language_name(code) for code in config.LANGUAGE_CODES],
        "scripts": {"ru": "кириллица", "de": "латиница с диакритикой"},
        "shared_letters": "",
    }
