"""Тир Пафнутия: план волн из слов переведённого текста.

Правила боя (скорость, урон, расписание, попадания) написаны на JavaScript и
проверяются набором tests/shooter_rules.test.js, который здесь запускается
через node, а если node нет — в движке V8 браузера Edge или Chrome
(tools/run_js_tests.py). Без node и браузера проверка пропускается: перевод
от неё не зависит.

Со стороны Python проверяется то, за что отвечает Python, — состав волн:
каждое слово текста выходит ровно один раз, волны растут, мини-боссы — самые
длинные слова в нужном порядке, у каждого слова есть немецкий перевод.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys

import pytest

from dragoman import config, game
from dragoman.collection import Collection

from .conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))
import run_js_tests  # noqa: E402


@pytest.fixture(scope="module")
def hamlet(translator):
    collection = Collection()
    entry = collection.get("lit-hamlet")
    return translator.translate(collection.text("lit-hamlet"), entry.title, entry.domain, log_unknown=False)


def letters(word: str) -> int:
    return len(re.sub(r"[^A-Za-zÀ-ÿ]", "", word))


def everyone(plan: game.Plan) -> list[game.Enemy]:
    return [e for w in plan.waves for e in w.enemies + [w.boss]]


@pytest.mark.parametrize("total, waves", [(10, 1), (15, 5), (100, 5), (287, 5), (31, 7), (1000, 10), (4, 3)])
def test_wave_sizes_grow_and_sum_up(total, waves):
    sizes = game.wave_sizes(total, waves)
    assert len(sizes) == waves and sum(sizes) == total
    assert sizes == sorted(sizes)
    if total >= 3 * waves * (waves + 1) // 2:
        assert all(a < b for a, b in zip(sizes, sizes[1:]))     # строго растут, когда слов хватает


@pytest.mark.parametrize("waves", [1, 3, 5, 8, 10])
def test_every_word_comes_exactly_once(hamlet, waves):
    plan = game.plan(hamlet, waves)
    words = game.collect_words(hamlet)
    enemies = everyone(plan)
    assert len(plan.waves) == waves
    assert sorted(e.en.lower() for e in enemies) == sorted(w["en"].lower() for w in words)
    assert len({e.id for e in enemies}) == len(enemies)
    assert plan.words == len(words) and plan.tokens == hamlet.stats["words"]


@pytest.mark.parametrize("waves", [3, 5, 10])
def test_waves_grow(hamlet, waves):
    sizes = [w.size for w in game.plan(hamlet, waves).waves]
    assert all(a < b for a, b in zip(sizes, sizes[1:])), sizes


@pytest.mark.parametrize("waves", [1, 5, 10])
def test_bosses_are_the_longest_words_in_order(hamlet, waves):
    plan = game.plan(hamlet, waves)
    bosses = [w.boss for w in plan.waves]
    # первую волну закрывает N-е по длине слово, последнюю — самое длинное
    lengths = [b.length for b in bosses]
    assert lengths == sorted(lengths)
    longest = max(letters(w["en"]) for w in game.collect_words(hamlet))
    assert bosses[-1].length == longest
    shortest_boss = min(lengths)
    assert all(e.length <= shortest_boss for w in plan.waves for e in w.enemies)
    assert plan.bosses == [b.en for b in bosses]
    assert all(b.kind == "boss" and b.hp >= max(6, b.length) for b in bosses)


def test_enemy_kinds(hamlet):
    enemies = [e for e in everyone(game.plan(hamlet, 5)) if e.kind != "boss"]
    kinds = {e.kind for e in enemies}
    assert kinds == {"swarm", "walker", "gunner"}
    for e in enemies:
        if e.pos == "VERB":
            assert e.kind == "gunner"
        elif e.kind == "swarm":
            assert e.pos in game.FUNCTION_POS and len(e.en) <= 4


def test_words_carry_german_translations(hamlet):
    enemies = everyone(game.plan(hamlet, 5))
    by_word = {e.en.lower(): e for e in enemies}
    assert by_word["tragedy"].de == "Tragödie"
    assert by_word["shakespeare"].en == by_word["shakespeare"].de == "Shakespeare"            # имя — без перевода и без склонения
    assert by_word["the"].kind == "swarm"
    translated = [e for e in enemies if e.translated]
    assert len(translated) / len(enemies) > 0.95
    assert all(e.de for e in enemies)


def test_waves_are_clamped(hamlet):
    low, high = config.SHOOTER_WAVES_RANGE
    assert len(game.plan(hamlet, 0).waves) == low
    assert len(game.plan(hamlet, 99).waves) == high


def test_small_text_gets_fewer_waves(translator):
    t = translator.translate("The spider translates words.", domain="cs", log_unknown=False)
    plan = game.plan(t, 10)
    assert len(plan.waves) == 1 and plan.waves[0].boss.en == "translates"


def test_plan_is_reproducible(hamlet):
    assert game.plan(hamlet, 5, seed=3).to_dict() == game.plan(hamlet, 5, seed=3).to_dict()


def test_document_tokens_rebuild_the_text(hamlet):
    paragraphs = game.document_tokens(hamlet)
    assert len(paragraphs) == len(hamlet.paragraphs)
    keys = {item["k"] for p in paragraphs for item in p if "k" in item}
    assert keys == {w["en"].lower() for w in game.collect_words(hamlet)}
    first = "".join(item["t"] + (" " if item["s"] else "") for item in paragraphs[0]).strip()
    heading, sentences = hamlet.english_paragraphs[0]
    assert first == " ".join(s.text for s in sentences)


# --- правила боя (JavaScript) ----------------------------------------------------------

def test_labels_use_base_forms(hamlet):
    """Над противником — именительный падеж того же числа и словарная форма прилагательного,
    а не форма из предложения («mit den Widersprüchen»)."""
    by_word = {w["en"].lower(): w["de"] for w in game.collect_words(hamlet)}
    assert by_word["contradictions"] == "Widersprüche"
    assert by_word["countries"] == "Länder"
    assert by_word["catholic"] == "katholisch"
    assert by_word["greatest"] == "am größten"


@pytest.mark.skipif(shutil.which("node") is None and run_js_tests.browser() is None,
                    reason="нет ни node, ни Edge/Chrome")
def test_javascript_rules():
    """tests/shooter_rules.test.js — в node, а без него в движке V8 браузера (tools/run_js_tests.py)."""
    result = subprocess.run([sys.executable, str(ROOT / "tools" / "run_js_tests.py")], capture_output=True,
                            text=True, encoding="utf-8", cwd=str(ROOT), timeout=300)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "ошибок: 0" in result.stdout
