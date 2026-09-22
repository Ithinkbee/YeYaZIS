"""Нейросетевой метод.

Первые два метода сравнивают профили напрямую заданной вручную метрикой.
Нейросетевой метод отличается тем, что решающее правило не задаётся, а
подбирается по обучающему корпусу: сеть сама выучивает, какие сочетания
частот признаков разделяют языки.

Правило построения образа: текст описывается вектором относительных частот
символьных N-грамм длиной 1–3 из фиксированного словаря признаков; словарь
отбирается на обучающем корпусе как объединение самых частых N-грамм каждого
языка, поэтому оба языка представлены в нём поровну.

Стратегия сравнения: двухслойный персептрон (скрытый слой с гиперболическим
тангенсом, выход — softmax) выдаёт вероятность принадлежности документа
каждому языку. Чтобы результат сравнивался с двумя другими методами в одной
шкале, расстоянием считается величина 1 − P(язык): у ближайшего языка она
наименьшая, как и в остальных методах.

Сеть реализована на numpy без внешних фреймворков: обучение занимает пару
секунд, а весь код обратного распространения умещается в одном методе, что
удобно для разбора на защите работы.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

import numpy as np

from .. import config
from ..models import Profile
from .base import Method, build_profile


def extract_features(
    normalized: str,
    n_range: tuple[int, int] = config.NEURAL_NGRAM_RANGE,
) -> Counter[str]:
    """Считает частоты символьных N-грамм, включая пробел между словами.

    Пробел не выбрасывается намеренно: N-граммы вида «` де`» и «`де `»
    несут сведения о том, какими буквами язык начинает и заканчивает слова.
    """
    text = f" {normalized} "
    counts: Counter[str] = Counter()
    for n in range(n_range[0], n_range[1] + 1):
        for start in range(len(text) - n + 1):
            counts[text[start : start + n]] += 1
    return counts


def fragments(text: str, size: int, step: int) -> list[str]:
    """Режет текст на перекрывающиеся фрагменты заданной длины."""
    if len(text) <= size:
        return [text] if text.strip() else []
    return [
        text[start : start + size]
        for start in range(0, len(text) - size + 1, step)
    ]


def multiscale_fragments(
    text: str,
    sizes: tuple[int, ...] = config.NEURAL_FRAGMENT_SIZES,
    overlap: float = config.NEURAL_FRAGMENT_OVERLAP,
) -> list[str]:
    """Собирает обучающие примеры нескольких длин сразу.

    Сеть должна одинаково уверенно узнавать язык и по строке, и по абзацу.
    Обучение только на длинных фрагментах приводит к тому, что на коротком
    входе вектор частот выглядит для сети непривычно разреженным и точность
    падает; набор длин эту зависимость устраняет.
    """
    pieces: list[str] = []
    for size in sizes:
        step = max(1, int(size * overlap))
        pieces.extend(fragments(text, size, step))
    return pieces


class NeuralMethod(Method):
    """Распознавание языка двухслойным персептроном."""

    code = "neural"
    title = "Нейросетевой метод"
    summary = "персептрон над частотами символьных N-грамм, выход softmax"
    description = (
        f"Документ описывается вектором частот {config.NEURAL_FEATURES} символьных "
        f"N-грамм длиной {config.NEURAL_NGRAM_RANGE[0]}–{config.NEURAL_NGRAM_RANGE[1]}. "
        f"Вектор подаётся на персептрон с одним скрытым слоем из "
        f"{config.NEURAL_HIDDEN} нейронов и softmax на выходе. Сеть обучается "
        "методом обратного распространения ошибки на фрагментах обучающего "
        "корпуса; расстоянием до языка считается 1 − P(язык)."
    )

    def __init__(self) -> None:
        super().__init__()
        #: словарь признаков: индекс -> N-грамма
        self.features: list[str] = []
        #: N-грамма -> индекс, для быстрой сборки вектора
        self._index: dict[str, int] = {}
        #: параметры сети
        self.w1: np.ndarray | None = None
        self.b1: np.ndarray | None = None
        self.w2: np.ndarray | None = None
        self.b2: np.ndarray | None = None
        #: среднее и разброс признаков на обучающем корпусе
        self.mean: np.ndarray | None = None
        self.std: np.ndarray | None = None
        #: порядок языков на выходе сети
        self.classes: list[str] = []
        #: кэш прямого прохода: сам профиль и посчитанные по нему вероятности.
        #: Профиль хранится целиком, а не его id: адреса освобождённых объектов
        #: переиспользуются, и кэш по id выдавал бы ответ от чужого документа.
        self._cache: tuple[Profile, np.ndarray] | None = None

    @property
    def trained(self) -> bool:
        return bool(self.profiles) and self.w1 is not None

    # --- признаки ------------------------------------------------------------

    def _select_features(self, corpus: dict[str, str]) -> list[str]:
        """Отбирает словарь признаков поровну от каждого языка.

        Если брать просто самые частые N-граммы объединённого корпуса, более
        объёмный язык вытеснит из словаря признаки второго. Поэтому от каждого
        языка берётся своя доля, после чего списки объединяются.
        """
        per_language = max(1, config.NEURAL_FEATURES // max(1, len(corpus)))
        selected: list[str] = []
        seen: set[str] = set()
        ranked = {
            code: [
                feature
                for feature, _ in sorted(
                    extract_features(text).items(),
                    key=lambda pair: (-pair[1], pair[0]),
                )
            ]
            for code, text in corpus.items()
        }
        # обход «по кругу»: первый признак каждого языка, второй каждого и т.д.
        for position in range(per_language):
            for code in sorted(ranked):
                if position < len(ranked[code]):
                    feature = ranked[code][position]
                    if feature not in seen:
                        seen.add(feature)
                        selected.append(feature)
        return selected[: config.NEURAL_FEATURES]

    def _vector(self, counts: Counter[str]) -> np.ndarray:
        """Собирает вектор относительных частот по словарю признаков."""
        total = sum(counts.values())
        if not total:
            return np.zeros(len(self.features), dtype=np.float64)
        return self._vector_from_weights(
            {feature: count / total for feature, count in counts.items()}
        )

    def _vector_from_weights(self, weights: dict[str, float]) -> np.ndarray:
        """Собирает вектор из готовых относительных частот.

        `build_profile` уже сохранил в профиле долю каждой N-граммы, поэтому
        восстанавливать из него целые частоты не нужно — и не следует: деление
        с последующим умножением теряло бы точность на редких признаках.
        """
        vector = np.zeros(len(self.features), dtype=np.float64)
        for feature, weight in weights.items():
            position = self._index.get(feature)
            if position is not None:
                vector[position] = weight
        return vector

    def _standardize(self, matrix: np.ndarray) -> np.ndarray:
        """Приводит признаки к нулевому среднему и единичному разбросу."""
        if self.mean is None or self.std is None:
            return matrix
        return (matrix - self.mean) / self.std

    # --- обучение ------------------------------------------------------------

    def fit(self, corpus: dict[str, str]) -> None:
        rng = np.random.default_rng(config.RANDOM_SEED)
        self.classes = [code for code in config.LANGUAGE_CODES if code in corpus]
        self.features = self._select_features(corpus)
        self._index = {feature: position for position, feature in enumerate(self.features)}

        # Корпус делится на обучающую и контрольную части ДО нарезки на
        # фрагменты: иначе перекрывающиеся фрагменты попали бы в обе выборки
        # и контрольная точность оказалась бы завышенной.
        train_rows: list[np.ndarray] = []
        train_labels: list[int] = []
        valid_rows: list[np.ndarray] = []
        valid_labels: list[int] = []
        for label, code in enumerate(self.classes):
            text = corpus[code]
            border = int(len(text) * (1.0 - config.NEURAL_VALIDATION_SPLIT))
            parts = (
                (text[:border], train_rows, train_labels),
                (text[border:], valid_rows, valid_labels),
            )
            for chunk, rows, labels in parts:
                for fragment in multiscale_fragments(chunk):
                    rows.append(self._vector(extract_features(fragment)))
                    labels.append(label)

        if not train_rows:
            raise ValueError("обучающий корпус слишком мал для нейросетевого метода")

        raw_train = np.vstack(train_rows)
        y_train = np.array(train_labels, dtype=np.int64)
        self.mean = raw_train.mean(axis=0)
        self.std = raw_train.std(axis=0)
        self.std[self.std < 1e-8] = 1.0  # признаки-константы не масштабируем
        x_train = self._standardize(raw_train)
        x_valid = self._standardize(np.vstack(valid_rows)) if valid_rows else None
        y_valid = np.array(valid_labels, dtype=np.int64) if valid_labels else None

        history = self._train_network(x_train, y_train, x_valid, y_valid, rng)

        # Образ языка для интерфейса — усреднённый вектор частот его фрагментов.
        # В решающем правиле он не участвует: язык выбирает сеть.
        self.profiles = {}
        for label, code in enumerate(self.classes):
            centroid = raw_train[y_train == label].mean(axis=0)
            # частоты домножены на миллион и округлены: build_profile принимает
            # целые счётчики, а относительные доли восстановит делением на сумму
            self.profiles[code] = build_profile(
                {
                    self.features[position]: int(value * 1_000_000)
                    for position, value in enumerate(centroid)
                    if value > 0
                },
                owner=code,
                method=self.code,
            )

        self.info.update(
            {
                "features": len(self.features),
                "hidden": config.NEURAL_HIDDEN,
                "epochs": config.NEURAL_EPOCHS,
                "train_fragments": int(x_train.shape[0]),
                "valid_fragments": int(x_valid.shape[0]) if x_valid is not None else 0,
                "fragment_sizes": list(config.NEURAL_FRAGMENT_SIZES),
                "classes": self.classes,
                **history,
            }
        )

    def _train_network(
        self,
        x_train: np.ndarray,
        y_train: np.ndarray,
        x_valid: np.ndarray | None,
        y_valid: np.ndarray | None,
        rng: np.random.Generator,
    ) -> dict[str, Any]:
        """Обратное распространение ошибки с оптимизатором Adam.

        Возвращает сведения о ходе обучения для отчёта.
        """
        n_features = x_train.shape[1]
        n_hidden = config.NEURAL_HIDDEN
        n_classes = len(self.classes)

        # инициализация Ксавье: разброс весов согласован с числом входов
        self.w1 = rng.normal(0.0, np.sqrt(1.0 / n_features), (n_features, n_hidden))
        self.b1 = np.zeros(n_hidden)
        self.w2 = rng.normal(0.0, np.sqrt(1.0 / n_hidden), (n_hidden, n_classes))
        self.b2 = np.zeros(n_classes)

        parameters = ["w1", "b1", "w2", "b2"]
        moment1 = {name: np.zeros_like(getattr(self, name)) for name in parameters}
        moment2 = {name: np.zeros_like(getattr(self, name)) for name in parameters}
        beta1, beta2, epsilon = 0.9, 0.999, 1e-8
        step = 0

        targets = np.zeros((y_train.size, n_classes))
        targets[np.arange(y_train.size), y_train] = 1.0

        best = {"accuracy": -1.0, "loss": float("inf")}
        best_weights: dict[str, np.ndarray] | None = None
        losses: list[float] = []

        for epoch in range(config.NEURAL_EPOCHS):
            order = rng.permutation(x_train.shape[0])
            epoch_loss = 0.0
            batches = 0
            for start in range(0, order.size, config.NEURAL_BATCH):
                rows = order[start : start + config.NEURAL_BATCH]
                x_batch, y_batch = x_train[rows], targets[rows]

                # прямой проход
                hidden_raw = x_batch @ self.w1 + self.b1
                hidden = np.tanh(hidden_raw)
                logits = hidden @ self.w2 + self.b2
                probabilities = _softmax(logits)

                loss = -np.mean(np.sum(y_batch * np.log(probabilities + 1e-12), axis=1))
                epoch_loss += loss
                batches += 1

                # обратный проход
                size = x_batch.shape[0]
                d_logits = (probabilities - y_batch) / size
                gradients = {
                    "w2": hidden.T @ d_logits + config.NEURAL_L2 * self.w2,
                    "b2": d_logits.sum(axis=0),
                }
                d_hidden = (d_logits @ self.w2.T) * (1.0 - hidden**2)
                gradients["w1"] = x_batch.T @ d_hidden + config.NEURAL_L2 * self.w1
                gradients["b1"] = d_hidden.sum(axis=0)

                # шаг Adam
                step += 1
                for name in parameters:
                    gradient = gradients[name]
                    moment1[name] = beta1 * moment1[name] + (1 - beta1) * gradient
                    moment2[name] = beta2 * moment2[name] + (1 - beta2) * gradient**2
                    corrected1 = moment1[name] / (1 - beta1**step)
                    corrected2 = moment2[name] / (1 - beta2**step)
                    setattr(
                        self,
                        name,
                        getattr(self, name)
                        - config.NEURAL_LEARNING_RATE * corrected1 / (np.sqrt(corrected2) + epsilon),
                    )

            losses.append(epoch_loss / max(1, batches))

            # контроль качества: запоминаем лучшие веса, а не последние
            if x_valid is not None and y_valid is not None and y_valid.size:
                accuracy, valid_loss = self._evaluate(x_valid, y_valid)
                if (accuracy, -valid_loss) > (best["accuracy"], -best["loss"]):
                    best = {"accuracy": accuracy, "loss": valid_loss, "epoch": epoch + 1}
                    best_weights = {name: getattr(self, name).copy() for name in parameters}

        if best_weights is not None:
            for name, value in best_weights.items():
                setattr(self, name, value)

        train_accuracy, train_loss = self._evaluate(x_train, y_train)
        return {
            "train_accuracy": round(train_accuracy, 4),
            "train_loss": round(train_loss, 5),
            "valid_accuracy": round(best["accuracy"], 4) if best["accuracy"] >= 0 else None,
            "best_epoch": best.get("epoch"),
            "loss_curve": [round(value, 5) for value in losses],
        }

    def _evaluate(self, features: np.ndarray, labels: np.ndarray) -> tuple[float, float]:
        """Доля верных ответов и значение функции потерь на выборке."""
        probabilities = self._forward(features)
        predicted = probabilities.argmax(axis=1)
        accuracy = float((predicted == labels).mean())
        loss = float(-np.mean(np.log(probabilities[np.arange(labels.size), labels] + 1e-12)))
        return accuracy, loss

    def _forward(self, features: np.ndarray) -> np.ndarray:
        """Прямой проход сети: вероятности языков."""
        hidden = np.tanh(features @ self.w1 + self.b1)
        return _softmax(hidden @ self.w2 + self.b2)

    # --- распознавание -------------------------------------------------------

    def profile(self, text: str) -> Profile:
        counts = extract_features(text)
        return build_profile(counts, owner="document", method=self.code)

    def _probabilities(self, document: Profile) -> np.ndarray:
        """Вероятности языков для профиля документа.

        `base.Method.classify` строит профиль один раз и передаёт один и тот же
        объект в `distance` для каждого языка. Кэш по идентичности объекта
        избавляет от повторного прямого прохода, из-за которого замер времени
        метода оказался бы завышен вдвое.

        В кэше удерживается ссылка на сам профиль. Это существенно: если
        хранить только `id`, освобождённый профиль может уступить свой адрес
        следующему, и метод вернёт вероятности, посчитанные для предыдущего
        документа.
        """
        if self._cache is not None and self._cache[0] is document:
            return self._cache[1]
        vector = self._standardize(self._vector_from_weights(document.weights).reshape(1, -1))
        probabilities = self._forward(vector)[0]
        self._cache = (document, probabilities)
        return probabilities

    def distance(self, document: Profile, language: Profile) -> float:
        probabilities = self._probabilities(document)
        if language.owner not in self.classes:
            return 1.0
        return float(1.0 - probabilities[self.classes.index(language.owner)])

    def explain(self, document: Profile, distances: dict[str, float]) -> dict[str, Any]:
        probabilities = self._probabilities(document)
        winner = int(probabilities.argmax())
        return {
            "profile_size": len(document),
            "probabilities": {
                code: float(probabilities[position])
                for position, code in enumerate(self.classes)
            },
            "top": [
                {"feature": feature.replace(" ", "␣"), "rank": rank, "weight": weight}
                for feature, rank, weight in document.top(15)
            ],
            "salient": self._salient_features(document, winner),
        }

    def _salient_features(self, document: Profile, target: int, count: int = 10) -> list[dict[str, Any]]:
        """Признаки, сильнее прочих склонившие сеть к выбранному языку.

        Вклад оценивается произведением значения признака на производную
        логита по нему — обычная карта значимости для небольшой сети.
        """
        raw = self._vector_from_weights(document.weights).reshape(1, -1)
        vector = self._standardize(raw)
        hidden = np.tanh(vector @ self.w1 + self.b1)
        # d logit_target / d x = w1 @ ((1 - tanh^2) * w2[:, target])
        gradient = self.w1 @ ((1.0 - hidden[0] ** 2) * self.w2[:, target])
        contribution = vector[0] * gradient
        order = np.argsort(-np.abs(contribution))[:count]
        return [
            {
                "feature": self.features[position].replace(" ", "␣"),
                "value": float(raw[0, position]),
                "contribution": float(contribution[position]),
            }
            for position in order
            if raw[0, position] > 0
        ]

    # --- сохранение ----------------------------------------------------------

    def _save_extra(self) -> dict[str, Any]:
        return {
            "features": self.features,
            "classes": self.classes,
            "w1": np.round(self.w1, 6).tolist(),
            "b1": np.round(self.b1, 6).tolist(),
            "w2": np.round(self.w2, 6).tolist(),
            "b2": np.round(self.b2, 6).tolist(),
            "mean": np.round(self.mean, 9).tolist(),
            "std": np.round(self.std, 9).tolist(),
        }

    def _load_extra(self, extra: dict[str, Any]) -> None:
        if not extra.get("features"):
            return
        self.features = list(extra["features"])
        self._index = {feature: position for position, feature in enumerate(self.features)}
        self.classes = list(extra.get("classes", config.LANGUAGE_CODES))
        self.w1 = np.array(extra["w1"], dtype=np.float64)
        self.b1 = np.array(extra["b1"], dtype=np.float64)
        self.w2 = np.array(extra["w2"], dtype=np.float64)
        self.b2 = np.array(extra["b2"], dtype=np.float64)
        self.mean = np.array(extra["mean"], dtype=np.float64)
        self.std = np.array(extra["std"], dtype=np.float64)
        self._cache = None


def _softmax(logits: np.ndarray) -> np.ndarray:
    """Softmax со сдвигом на максимум — защита от переполнения экспоненты."""
    shifted = logits - logits.max(axis=-1, keepdims=True)
    exponents = np.exp(shifted)
    return exponents / exponents.sum(axis=-1, keepdims=True)
