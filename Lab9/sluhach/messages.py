"""Ответы системы на немецком и на русском.

Ответ звучит голосом и одновременно появляется в облачке Пафнутия, поэтому
написан от его лица: коротко, по делу и так, чтобы синтезатор речи прочёл
без запинки — без сокращений и скобок. Каждый ответ есть на обоих языках:
система отвечает на том языке, на котором её слушают, а русский вариант
немецкого ответа показывается в журнале как перевод.
"""

from __future__ import annotations

from typing import Callable

from sluhach.text import plural_de, plural_ru

_PARAGRAPHS_RU = ("абзац", "абзаца", "абзацев")
_SENTENCES_RU = ("предложение", "предложения", "предложений")
_WORDS_RU = ("слово", "слова", "слов")
_TIMES_RU = ("раз", "раза", "раз")
_HOURS_RU = ("час", "часа", "часов")
_MINUTES_RU = ("минута", "минуты", "минут")


def _ru(number: int, forms: tuple[str, str, str]) -> str:
    return f"{number} {plural_ru(number, *forms)}"


def _de(number: int, one: str, many: str) -> str:
    return f"{number} {plural_de(number, one, many)}"


def _volume_ru(f: dict) -> str:
    return f"{_ru(f['words'], _WORDS_RU)}, {_ru(f['sentences'], _SENTENCES_RU)} и {_ru(f['paragraphs'], _PARAGRAPHS_RU)}"


def _volume_de(f: dict) -> str:
    return (f"{_de(f['words'], 'Wort', 'Wörter')}, {_de(f['sentences'], 'Satz', 'Sätze')} "
            f"und {_de(f['paragraphs'], 'Absatz', 'Absätze')}")


def _times_de(count: int) -> str:
    return "einmal" if count == 1 else f"{count}-mal"


def _closed(title: str) -> str:
    """Название в перечислении: с точкой, если оно само не кончается знаком («Татьяна любит…»)."""
    return title if title[-1:] in ".!?…" else title + "."


#: повод -> (ответ по-немецки, ответ по-русски). Поля приходят словарём.
TEXTS: dict[str, tuple[Callable[[dict], str], Callable[[dict], str]]] = {
    "help": (
        lambda f: f"Sagen Sie einen Befehl, ich führe ihn aus. Zum Beispiel: {f['examples']}. "
                  "Alle Befehle stehen auf der Seite „Operationen“.",
        lambda f: f"Скажите команду — я выполню. Например: {f['examples']}. "
                  "Все команды — на странице «Операции».",
    ),
    "list": (
        lambda f: f"Es gibt {_de(f['count'], 'Aufsatz', 'Aufsätze')}. {f['titles']}",
        lambda f: f"Сочинений: {f['count']}. {f['titles']}",
    ),
    "list_item": (
        lambda f: f"Nummer {f['number']}: {_closed(f['title'])}",
        lambda f: f"Номер {f['number']}: {_closed(f['title'])}",
    ),
    "list_empty": (
        lambda f: "Auf Deutsch habe ich keine Aufsätze im Netz.",
        lambda f: "На русском в моей паутине сочинений нет.",
    ),
    "open": (
        lambda f: f"Ich öffne den Aufsatz „{f['title']}“: {f['about']}. "
                  f"Er hat {_de(f['paragraphs'], 'Absatz', 'Absätze')}.",
        lambda f: f"Открываю сочинение «{f['title']}»: {f['about']}. "
                  f"В нём {_ru(f['paragraphs'], _PARAGRAPHS_RU)}.",
    ),
    "open_unknown": (
        lambda f: f"Den Aufsatz „{f['query']}“ habe ich nicht im Netz. Sagen Sie: „Liste der Aufsätze“.",
        lambda f: f"Сочинения «{f['query']}» в моей паутине нет. Скажите: «список сочинений».",
    ),
    "open_number": (
        lambda f: f"Aufsatz Nummer {f['number']} gibt es nicht. Es sind nur {f['count']}.",
        lambda f: f"Сочинения номер {f['number']} нет. Их всего {f['count']}.",
    ),
    "need_essay": (
        lambda f: "Öffnen Sie zuerst einen Aufsatz. Sagen Sie: „Liste der Aufsätze“.",
        lambda f: "Сначала откройте сочинение. Скажите: «список сочинений».",
    ),
    "essay_last": (
        lambda f: "Das ist der letzte Aufsatz der Liste.",
        lambda f: "Это последнее сочинение в списке.",
    ),
    "essay_first": (
        lambda f: "Das ist der erste Aufsatz der Liste.",
        lambda f: "Это первое сочинение в списке.",
    ),
    "close": (
        lambda f: "Geschlossen. Hier ist wieder die Liste.",
        lambda f: "Закрыл. Перед вами снова список.",
    ),
    "close_nothing": (
        lambda f: "Es ist kein Aufsatz geöffnet.",
        lambda f: "Закрывать нечего: сочинение не открыто.",
    ),
    # чтение вслух: голосом — сам абзац, в облачке — его начало
    "read_section": (
        lambda f: f"Abschnitt: {f['section']}.",
        lambda f: f"Раздел: {f['section']}.",
    ),
    "read_display": (
        lambda f: f"Ich lese Absatz {f['number']} von {f['count']}: „{f['preview']}“",
        lambda f: f"Читаю абзац {f['number']} из {f['count']}: «{f['preview']}»",
    ),
    "read_gloss": (
        lambda f: f"читает абзац {f['number']} из {f['count']}",
        lambda f: f"читает абзац {f['number']} из {f['count']}",
    ),
    "paragraph_last": (
        lambda f: "Weiter geht es nicht: Das ist der letzte Absatz.",
        lambda f: "Дальше ничего нет: это последний абзац.",
    ),
    "paragraph_first": (
        lambda f: "Davor steht nichts: Das ist der erste Absatz.",
        lambda f: "Раньше ничего нет: это первый абзац.",
    ),
    "goto_missing": (
        lambda f: f"Absatz {f['number']} gibt es nicht. Der Aufsatz hat nur {f['count']}.",
        lambda f: f"Абзаца {f['number']} нет. В сочинении их {f['count']}.",
    ),
    "goto_unknown": (
        lambda f: "Die Nummer des Absatzes habe ich nicht verstanden.",
        lambda f: "Номер абзаца я не разобрал.",
    ),
    "info": (
        lambda f: f"Aufsatz „{f['title']}“: {f['about']}. Umfang: {_volume_de(f)}.",
        lambda f: f"Сочинение «{f['title']}»: {f['about']}. Объём: {_volume_ru(f)}.",
    ),
    "count": (
        lambda f: f"Der Aufsatz hat {_volume_de(f)}.",
        lambda f: f"В сочинении {_volume_ru(f)}.",
    ),
    "find": (
        lambda f: f"Das Wort „{f['word']}“ kommt {_times_de(f['count'])} vor. "
                  f"Die nächste Stelle ist Absatz {f['number']}.",
        lambda f: f"Слово «{f['word']}» встречается {_ru(f['count'], _TIMES_RU)}. "
                  f"Ближайшее место — абзац {f['number']}.",
    ),
    "find_none": (
        lambda f: f"Das Wort „{f['word']}“ kommt in diesem Aufsatz nicht vor.",
        lambda f: f"Слова «{f['word']}» в этом сочинении нет.",
    ),
    "where": (
        lambda f: f"Aufsatz „{f['title']}“, Absatz {f['number']} von {f['count']}.",
        lambda f: f"Сочинение «{f['title']}», абзац {f['number']} из {f['count']}.",
    ),
    "where_list": (
        lambda f: "Kein Aufsatz ist geöffnet. Sie sehen die Liste.",
        lambda f: "Сочинение не открыто. Перед вами список.",
    ),
    # диктовка: записанная фраза не произносится, говорится только о начале и о конце.
    # Голосом о начале — одно слово: пока система говорит, она не слушает, а диктовать
    # начинают сразу. Подсказка о знаках показывается только текстом
    "dictate": (
        lambda f: "Diktieren Sie.",
        lambda f: "Диктуйте.",
    ),
    "dictate_hint": (
        lambda f: "Diktieren Sie. Satzzeichen sagen Sie an: Komma, Punkt, neuer Absatz."
                  + (f" Zum Schluss sagen Sie: „{f['end']}“." if f["end"] else ""),
        lambda f: "Диктуйте. Знаки называйте словами: запятая, точка, новый абзац."
                  + (f" В конце скажите: «{f['end']}»." if f["end"] else ""),
    ),
    "dictate_saved": (
        lambda f: f"Gespeichert: Aufsatz „{f['title']}“, {_de(f['words'], 'Wort', 'Wörter')}. Er ist jetzt geöffnet.",
        lambda f: f"Сохранил сочинение «{f['title']}»: {_ru(f['words'], _WORDS_RU)}. Оно открыто.",
    ),
    "dictate_empty": (
        lambda f: "Diktat beendet. Es gab nichts zu speichern.",
        lambda f: "Диктовка окончена. Сохранять нечего.",
    ),
    "dictate_closed": (
        lambda f: "Diktat beendet.",
        lambda f: "Диктовка окончена.",
    ),
    "dictate_none": (
        lambda f: "Es läuft kein Diktat.",
        lambda f: "Диктовка не идёт.",
    ),
    "dictate_limit": (
        lambda f: f"Es gibt schon {_de(f['count'], 'diktierten Aufsatz', 'diktierte Aufsätze')}. "
                  "Löschen Sie einen, dann speichere ich.",
        lambda f: f"Надиктованных сочинений уже {f['count']}. Удалите лишнее — и я сохраню.",
    ),
    "dictate_full": (
        lambda f: "Der Entwurf ist voll. Beenden Sie das Diktat.",
        lambda f: "Черновик заполнен. Закончите диктовку.",
    ),
    "dictate_undo": (
        lambda f: f"Gelöscht: {f['piece']}",
        lambda f: f"Стёр: {f['piece']}",
    ),
    "dictate_undo_nothing": (
        lambda f: "Es gibt nichts zu löschen.",
        lambda f: "Стирать нечего.",
    ),
    "language": (
        lambda f: "Gut, ab jetzt spreche ich Deutsch.",
        lambda f: "Хорошо, дальше говорю по-русски.",
    ),
    "language_same": (
        lambda f: "Ich spreche schon Deutsch.",
        lambda f: "Я и так говорю по-русски.",
    ),
    "language_unknown": (
        lambda f: "Ich kann Deutsch und Russisch. Welche Sprache soll es sein?",
        lambda f: "Я умею по-немецки и по-русски. Какой язык выбрать?",
    ),
    "repeat_nothing": (
        lambda f: "Es gibt noch nichts zu wiederholen.",
        lambda f: "Повторять пока нечего.",
    ),
    # время — словами, а не «14:05»: так его без ошибок читает любой синтезатор
    "time": (
        lambda f: f"Es ist {f['hour']} Uhr" + (f" {f['minute']}." if f["minute"] else "."),
        lambda f: f"Сейчас {_ru(f['hour'], _HOURS_RU)}" + (f" {_ru(f['minute'], _MINUTES_RU)}." if f["minute"] else " ровно."),
    ),
    "stop": (
        lambda f: "Ich bin still.",
        lambda f: "Молчу.",
    ),
    "sleep": (
        lambda f: "Ich höre nicht mehr zu. Drücken Sie die Taste, wenn Sie mich brauchen.",
        lambda f: "Больше не слушаю. Понадоблюсь — нажмите кнопку.",
    ),
    "game": (
        lambda f: "Gehen wir spazieren. Sprechen Sie nur laut genug.",
        lambda f: "Идём гулять. Только говорите погромче.",
    ),
    # операция не найдена: система повторяет услышанное
    "echo": (
        lambda f: f"Ich wiederhole: {f['phrase']}.",
        lambda f: f"Повторяю: {f['phrase']}.",
    ),
}


def render(key: str, language: str, **fields) -> str:
    """Ответ по поводу на языке; для неизвестного языка — по-русски."""
    german, russian = TEXTS[key]
    return (german if language == "de" else russian)(fields)
