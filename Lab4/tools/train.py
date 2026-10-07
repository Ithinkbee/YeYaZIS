"""Обучение анализатора английского языка: лемматизатор, теггер, синтаксический анализатор.

    python tools/train.py                обучить всё и сохранить в models/
    python tools/train.py --check        только проверить сохранённые модели на тестовых частях
    python tools/train.py --quick        одна эпоха на тысяче предложений (проверка кода)

Корпуса Universal Dependencies English EWT и GUM (≈ 24 тыс. размеченных
предложений, ≈ 400 тыс. слов) при первом запуске скачиваются в data/treebank;
синтаксический анализатор учится ещё и на LinES и ParTUT (в них нет тегов
Penn Treebank, теги расставляет теггер) — всего ≈ 29 тыс. предложений.
Учатся три модели:

1. лемматизатор — правила окончаний и список неправильных форм;
2. теггер Penn Treebank — усреднённый перцептрон;
3. анализатор зависимостей arc-hybrid и разметчик отношений.

Анализатор учится на тегах, расставленных теггером, а не на эталонных: иначе
при работе он видел бы теги другого качества, чем при обучении. Чтобы теггер
не размечал предложения, на которых сам учился (там он почти безошибочен),
обучающая часть размечается перекрёстно — пятью теггерами, каждый из которых
не видел свою пятую часть корпуса.

Итоги проверки на тестовых частях корпусов сохраняются в report/analyzer.json.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dragoman import config, console  # noqa: E402
from dragoman.english import conllu  # noqa: E402
from dragoman.english.lemmatizer import Lemmatizer  # noqa: E402
from dragoman.english.parser import Parser  # noqa: E402
from dragoman.english.tagger import Tagger  # noqa: E402

console.setup()

PARTS = ("train", "dev", "test")


def download() -> None:
    config.TREEBANK_DIR.mkdir(parents=True, exist_ok=True)
    for name, base in {**config.TREEBANKS, **config.PARSER_TREEBANKS}.items():
        for part in PARTS:
            path = config.TREEBANK_DIR / f"{name}-ud-{part}.conllu"
            if path.exists() and path.stat().st_size > 0:
                continue
            url = f"{base}/{name}-ud-{part}.conllu"
            print(f"  загрузка {url}")
            with urllib.request.urlopen(url, timeout=120) as response:
                path.write_bytes(response.read())


def load(part: str, names=None) -> dict[str, list[conllu.TreeSentence]]:
    names = names or config.TREEBANKS
    return {name: conllu.read(config.TREEBANK_DIR / f"{name}-ud-{part}.conllu") for name in names}


def evaluate(tagger: Tagger, parser: Parser | None, lemmatizer: Lemmatizer,
             sentences: list[conllu.TreeSentence], penn: bool = True) -> dict:
    """Точность тегов и лемм, UAS и LAS (без знаков препинания, по правилам CoNLL)."""
    tags_ok = lemmas_ok = lemmas_total = words = 0
    uas = las = scored = 0
    started = time.perf_counter()
    for sentence in sentences:
        predicted = tagger.tag(sentence.words)
        heads, labels = parser.parse(sentence.words, predicted) if parser else ([], [])
        for i, token in enumerate(sentence.tokens):
            words += 1
            tags_ok += predicted[i] == token.xpos
            if token.xpos not in {"NNP", "NNPS"} and token.lemma != "_" and any(c.isalpha() for c in token.form):
                lemmas_total += 1
                gold = token.lemma if token.lemma == "I" else token.lemma.lower()
                lemmas_ok += lemmatizer.lemma(token.form, predicted[i]) == gold
            if parser and token.upos != "PUNCT":
                scored += 1
                if heads[i] == token.head:
                    uas += 1
                    las += labels[i] == token.deprel
    elapsed = time.perf_counter() - started
    return {
        "sentences": len(sentences), "words": words,
        "tagging": tags_ok / max(1, words) if penn else None,
        "lemmas": lemmas_ok / max(1, lemmas_total) if penn else None,
        "uas": uas / max(1, scored) if parser else None, "las": las / max(1, scored) if parser else None,
        "ms_per_sentence": 1000 * elapsed / max(1, len(sentences)),
    }


def jackknife(train: list[conllu.TreeSentence], folds: int, epochs: int) -> list[list[str]]:
    """Теги обучающих предложений от теггеров, не видевших эти предложения."""
    predicted: list[list[str]] = [[] for _ in train]
    for fold in range(folds):
        held = [i for i in range(len(train)) if i % folds == fold]
        rest = [(s.words, s.tags) for i, s in enumerate(train) if i % folds != fold]
        tagger = Tagger()
        tagger.train(rest, epochs=epochs, seed=config.RANDOM_SEED + fold, log=lambda *_: None)
        right = total = 0
        for i in held:
            predicted[i] = tagger.tag(train[i].words)
            right += sum(p == g for p, g in zip(predicted[i], train[i].tags))
            total += len(train[i])
        print(f"    часть {fold + 1}/{folds}: точность тегов {100 * right / max(1, total):.2f} %")
    return predicted


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="только проверить сохранённые модели")
    parser.add_argument("--quick", action="store_true", help="одна эпоха на тысяче предложений")
    arguments = parser.parse_args()

    config.ensure_dirs()
    download()
    started = time.perf_counter()
    train_parts, test_parts = load("train"), load("test")
    extra_parts, extra_tests = load("train", config.PARSER_TREEBANKS), load("test", config.PARSER_TREEBANKS)
    train = [s for name in config.TREEBANKS for s in train_parts[name]]
    extra = [s for name in config.PARSER_TREEBANKS for s in extra_parts[name]]
    if arguments.quick:
        train = train[:1000]
    print(f"Обучающие предложения: {len(train)}, слов: {sum(len(s) for s in train)}")

    if arguments.check:
        tagger, analyzer = Tagger.load(config.MODELS_DIR), Parser.load(config.MODELS_DIR)
        lemmatizer = Lemmatizer.load(config.MODELS_DIR)
        train = train + extra                    # сколько предложений видел анализатор
    else:
        epochs = (1, 1, 1) if arguments.quick else (config.TAGGER_EPOCHS, config.PARSER_EPOCHS, config.LABELER_EPOCHS)
        print("1. Лемматизатор")
        lemmatizer = Lemmatizer()
        print("   ", lemmatizer.train([(t.form, t.xpos, t.lemma) for s in train for t in s.tokens]))
        lemmatizer.save(config.MODELS_DIR)

        print("2. Теггер: перекрёстная разметка обучающих предложений")
        folds = 2 if arguments.quick else config.JACKKNIFE_FOLDS
        tags = jackknife(train, folds, 1 if arguments.quick else max(3, config.TAGGER_EPOCHS - 2))
        print("   теггер на всём корпусе")
        tagger = Tagger()
        tagger.train([(s.words, s.tags) for s in train], epochs=epochs[0], seed=config.RANDOM_SEED)
        print("   сохранено:", tagger.save(config.MODELS_DIR))

        print("3. Синтаксический анализатор")
        if not arguments.quick:
            # корпуса без тегов Penn: теги расставляет теггер, который этих предложений не видел
            train = train + extra
            tags = tags + [tagger.tag(s.words) for s in extra]
            print(f"   с корпусами {', '.join(config.PARSER_TREEBANKS)}: {len(train)} предложений")
        usable = [(s, t) for s, t in zip(train, tags) if conllu.is_projective(s.heads)]
        print(f"   проективных деревьев: {len(usable)} из {len(train)}")
        analyzer = Parser()
        analyzer.train([(s.words, t, s.heads) for s, t in usable], epochs=epochs[1], seed=config.RANDOM_SEED)
        analyzer.train_labeler([(s.words, t, s.heads, s.labels) for s, t in usable], epochs=epochs[2],
                               seed=config.RANDOM_SEED)
        print("   сохранено:", analyzer.save(config.MODELS_DIR))

    print("4. Проверка на тестовых частях корпусов")
    report = {"treebanks": {}, "train_sentences": len(train), "train_words": sum(len(s) for s in train)}
    for name, sentences in list(test_parts.items()) + list(extra_tests.items()):
        penn = name in config.TREEBANKS
        result = evaluate(tagger, analyzer, lemmatizer, sentences, penn=penn)
        report["treebanks"][name] = result
        tags_text = f"теги {100 * result['tagging']:.2f} %, леммы {100 * result['lemmas']:.2f} %, " if penn else ""
        print(f"   {name}: {tags_text}UAS {100 * result['uas']:.2f} %, LAS {100 * result['las']:.2f} %, "
              f"{result['ms_per_sentence']:.1f} мс на предложение")
    report["models"] = {path.name: path.stat().st_size for path in sorted(config.MODELS_DIR.glob("*"))
                        if path.is_file()}
    report["seconds"] = round(time.perf_counter() - started, 1)
    previous = config.REPORT_DIR / "analyzer.json"
    if arguments.check and previous.exists():
        # проверка не переобучает модели: время обучения остаётся от последнего обучения
        report["check_seconds"] = report["seconds"]
        report["seconds"] = json.loads(previous.read_text(encoding="utf-8")).get("seconds", report["seconds"])
    if not arguments.quick:
        (config.REPORT_DIR / "analyzer.json").write_text(json.dumps(report, ensure_ascii=False, indent=1),
                                                         encoding="utf-8")
    print(f"Готово за {report.get('check_seconds', report['seconds']):.0f} с")
    return 0


if __name__ == "__main__":
    sys.exit(main())
