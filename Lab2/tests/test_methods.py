"""Проверка методов распознавания и их метрик."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolmach import config, methods, preprocess  # noqa: E402
from tolmach.methods.alphabet import AlphabetMethod, extract_letters  # noqa: E402
from tolmach.methods.base import build_profile  # noqa: E402
from tolmach.methods.neural import NeuralMethod, extract_features, multiscale_fragments  # noqa: E402
from tolmach.methods.ngram import NgramMethod, extract_ngrams  # noqa: E402

RUSSIAN = preprocess.normalize(
    "Пчелиную семью правильнее рассматривать не как множество насекомых, а как "
    "единый организм. Отдельная пчела вне семьи живёт считаные дни и не способна "
    "ни размножаться, ни поддерживать нужную температуру. Семья же переживает "
    "зиму, растёт, делится и ведёт себя как самостоятельное существо, в котором "
    "отдельные особи играют роль клеток. Распределение работ внутри семьи "
    "связано с возрастом рабочей пчелы, и порядок этот не задан жёстко. "
    "Соты строятся из воска, который пчёлы выделяют особыми железами."
)

GERMAN = preprocess.normalize(
    "Ein Bienenvolk betrachtet man treffender nicht als eine Menge von Insekten, "
    "sondern als einen einzigen Organismus. Die einzelne Biene lebt außerhalb des "
    "Volkes nur wenige Tage und kann sich weder fortpflanzen noch die nötige Wärme "
    "halten. Das Volk dagegen überwintert, wächst, teilt sich und verhält sich wie "
    "ein eigenständiges Lebewesen, in dem die einzelnen Tiere die Rolle von Zellen "
    "übernehmen. Die Verteilung der Arbeiten hängt vom Alter ab, und die Waben "
    "entstehen aus Wachs, das die Bienen mit besonderen Drüsen ausscheiden."
)

CORPUS = {"ru": RUSSIAN, "de": GERMAN}


@pytest.fixture(scope="module")
def trained() -> dict[str, methods.Method]:
    """Все три метода, обученные на маленьком корпусе из двух абзацев."""
    built = methods.create_all()
    for method in built.values():
        method.fit(CORPUS)
    return built


# --- общее поведение всех методов -------------------------------------------


@pytest.mark.parametrize("code", methods.METHOD_CODES)
def test_method_recognizes_its_own_training_text(trained, code):
    """Текст обучающего корпуса обязан опознаваться как свой язык."""
    method = trained[code]
    assert method.classify(RUSSIAN).language == "ru"
    assert method.classify(GERMAN).language == "de"


@pytest.mark.parametrize("code", methods.METHOD_CODES)
def test_distance_is_normalised(trained, code):
    """Метрика должна лежать в [0, 1], иначе методы несравнимы между собой."""
    for text in (RUSSIAN, GERMAN):
        for value in trained[code].distances(text).values():
            assert 0.0 <= value <= 1.0


@pytest.mark.parametrize("code", methods.METHOD_CODES)
def test_untrained_method_refuses_to_classify(code):
    method = methods.create(code)
    with pytest.raises(RuntimeError, match="не обучен"):
        method.classify("какой-то текст")


@pytest.mark.parametrize("code", methods.METHOD_CODES)
def test_save_and_load_roundtrip(trained, code, tmp_path):
    """Профили с диска должны давать в точности те же расстояния."""
    original = trained[code]
    original.save(tmp_path)

    restored = methods.create(code)
    assert restored.load(tmp_path)

    for text in (RUSSIAN, GERMAN):
        before = original.distances(text)
        after = restored.distances(text)
        assert before.keys() == after.keys()
        for language in before:
            assert before[language] == pytest.approx(after[language], abs=1e-6)


@pytest.mark.parametrize("code", methods.METHOD_CODES)
def test_load_missing_model_returns_false(code, tmp_path):
    assert methods.create(code).load(tmp_path) is False


@pytest.mark.parametrize("code", methods.METHOD_CODES)
def test_classification_is_deterministic(trained, code):
    """Один и тот же текст обязан давать один и тот же ответ.

    Проверка ловит ошибки кэширования: если кэш метода привязан к чему-то
    ненадёжному, второй вызов вернёт результат от предыдущего документа.
    """
    first = trained[code].classify(RUSSIAN)
    second = trained[code].classify(RUSSIAN)
    assert first.language == second.language
    assert first.distances == second.distances


@pytest.mark.parametrize("code", methods.METHOD_CODES)
def test_alternating_documents_do_not_leak(trained, code):
    """Чередование языков не должно путать метод.

    Именно так проявлялась ошибка кэша по `id`: освобождённый профиль отдавал
    свой адрес следующему, и метод повторял ответ для предыдущего текста.
    """
    for _ in range(40):
        assert trained[code].classify(RUSSIAN).language == "ru"
        assert trained[code].classify(GERMAN).language == "de"


# --- метод N-грамм -----------------------------------------------------------


def test_extract_ngrams_pads_words():
    counts = extract_ngrams("да", max_n=3)
    assert counts["_д"] == 1      # начало слова
    assert counts["а_"] == 1      # конец слова
    assert counts["_да"] == 1
    assert counts["д"] == 1


def test_ngram_profile_is_limited():
    method = NgramMethod(profile_size=25)
    method.fit(CORPUS)
    assert len(method.profiles["ru"]) == 25
    assert len(method.profile(RUSSIAN)) == 25


def test_out_of_place_distance_is_zero_for_identical_profiles():
    method = NgramMethod()
    method.fit(CORPUS)
    profile = method.profile(RUSSIAN)
    assert method.distance(profile, profile) == pytest.approx(0.0)


def test_missing_ngrams_cost_the_maximum_penalty():
    """N-грамме, которой нет в профиле языка, назначается полный штраф."""
    method = NgramMethod(profile_size=10)
    document = build_profile({"ща": 5}, owner="d", method="ngram", limit=10)
    language = build_profile({"zz": 5}, owner="de", method="ngram", limit=10)
    assert method.distance(document, language) == pytest.approx(1.0)


def test_empty_text_gives_maximum_distance():
    method = NgramMethod()
    method.fit(CORPUS)
    assert method.distance(method.profile(""), method.profiles["ru"]) == 1.0


# --- алфавитный метод --------------------------------------------------------


def test_extract_letters_skips_spaces():
    counts = extract_letters("аб аб")
    assert counts["а"] == 2 and counts["б"] == 2
    assert " " not in counts


def test_alphabets_do_not_overlap():
    """Кириллица и латиница не пересекаются — на этом держится метод."""
    method = AlphabetMethod()
    method.fit(CORPUS)
    assert not method.alphabets["ru"] & method.alphabets["de"]
    assert "ё" in method.alphabets["ru"] or "е" in method.alphabets["ru"]
    assert {"ä", "ü", "ß"} & method.alphabets["de"]


def test_alphabet_coverage_separates_languages():
    method = AlphabetMethod()
    method.fit(CORPUS)
    profile = method.profile(RUSSIAN)
    assert method.coverage(profile, "ru") > 0.95
    assert method.coverage(profile, "de") < 0.05


def test_alphabet_distance_is_symmetric_in_form():
    method = AlphabetMethod()
    method.fit(CORPUS)
    russian = method.profile(RUSSIAN)
    german = method.profile(GERMAN)
    # разные системы письма — расстояние близко к максимуму
    assert method.distance(russian, method.profiles["de"]) > 0.9
    assert method.distance(german, method.profiles["ru"]) > 0.9


# --- нейросетевой метод ------------------------------------------------------


def test_extract_features_includes_word_boundaries():
    counts = extract_features("да", (1, 3))
    assert counts[" д"] == 1
    assert counts["а "] == 1


def test_multiscale_fragments_cover_several_lengths():
    text = "а" * 2000
    pieces = multiscale_fragments(text, sizes=(150, 600), overlap=0.5)
    lengths = {len(piece) for piece in pieces}
    assert 150 in lengths and 600 in lengths


def test_neural_probabilities_sum_to_one(trained):
    method = trained["neural"]
    detail = method.classify(GERMAN).detail
    assert sum(detail["probabilities"].values()) == pytest.approx(1.0)


def test_neural_distance_is_one_minus_probability(trained):
    method = trained["neural"]
    result = method.classify(RUSSIAN)
    detail = result.detail
    for code, probability in detail["probabilities"].items():
        assert result.distances[code] == pytest.approx(1.0 - probability, abs=1e-9)


def test_neural_training_reaches_full_accuracy(trained):
    assert trained["neural"].info["train_accuracy"] == 1.0


def test_neural_is_reproducible():
    """Одно и то же зерно обязано давать одни и те же веса."""
    first, second = NeuralMethod(), NeuralMethod()
    first.fit(CORPUS)
    second.fit(CORPUS)
    assert first.classify(RUSSIAN).distances == second.classify(RUSSIAN).distances


# --- реестр -------------------------------------------------------------------


def test_registry_matches_config_order():
    assert methods.METHOD_CODES == tuple(cls.code for cls in methods.METHOD_CLASSES)
    assert set(methods.create_all()) == set(methods.METHOD_CODES)


def test_unknown_method_raises():
    with pytest.raises(KeyError):
        methods.create("нет-такого")


def test_every_method_is_described():
    for entry in methods.describe():
        assert entry["title"] and entry["summary"] and entry["description"]


def test_language_codes_cover_variant():
    assert set(config.LANGUAGE_CODES) == {"ru", "de"}
