"""Пафнутий — паук из прошлых лабораторных работ.

В «Арахне» он комментировал поисковую выдачу, в «Толмаче» играл в шахматы,
в «Изборнике» воевал со словами, в «Слухаче» гулял, слушаясь голоса. Здесь
он наконец заговорил сам: у него собственный голос — формантный синтезатор
системы или нейросетевой Thorsten, поднятый на полоктавы, — и своя вкладка
«Мой говорящий Пафнутий», где он, как кот из «Говорящего Тома», повторяет
сказанное писклявым голосом, отзывается на тычки и просит мух.

Характер прежний — немногословен, самодоволен, всё меряет паутиной и
мухами. Говорит он по-немецки (это язык варианта), а в облачке рядом —
перевод. Реплики в углу страниц — по-русски. Подбираются по поводу, а не
случайно из общего мешка. Выключается переменной GLASHATAI_COMPANION.
"""

from __future__ import annotations

import random

NAME = "Пафнутий"
NAME_GENITIVE = "Пафнутия"

#: реплики в углу страниц, по-русски
LINES: dict[str, tuple[str, ...]] = {
    "idle": (
        "Паутина натянута. Жду текст.",
        "Восемь лап, один голос. Немецкий.",
        "Сижу в углу, читаю про себя.",
    ),
    "reader": (
        "Дай текст — прочту вслух. Даже «z. B.» и «O(n log n)».",
        "Год 1954 я читаю как год, а не как количество.",
        "Скопируй текст откуда угодно — прочту.",
        "Голосов у меня много. Свой — самый звонкий.",
    ),
    "articles": (
        "Наведи лапу — то есть мышь — на предложение.",
        "Научные статьи — моя слабость. После мух.",
        "Щёлкни по предложению — начну с него.",
    ),
    "elsewhere": (
        "Выдели текст где угодно и нажми Ctrl+Alt+R.",
        "Паутина длинная: дотянусь до любой программы.",
        "Закладку перетащи на панель — и я приду на любую страницу.",
    ),
    "lexicon": (
        "Здесь записано, как читать трудные слова.",
        "«Cloud» — «Клауд». Не «Клут». Запомни.",
        "Впиши слово — прочту по-твоему.",
    ),
    "evaluation": (
        "Синтезатор говорит, распознаватель слушает. Честный экзамен.",
        "Мой собственный голос тоже сдавал. Не смейся.",
        "Цифры не врут. Иногда недоговаривают.",
    ),
    "help": (
        "Читай. Потом слушай.",
        "Всё описано. Даже я.",
    ),
    "talking": (
        "Скажи что-нибудь — повторю.",
        "Тыкни — отвечу. Тыкни сильно — обижусь.",
    ),
}

#: реплики «Говорящего Пафнутия»: (по-немецки, перевод, манера голоса Thorsten)
TALK: dict[str, tuple[tuple[str, str, str], ...]] = {
    "hello": (
        ("Hallo! Ich bin Pafnutij.", "Привет! Я Пафнутий.", "amused"),
        ("Guten Tag! Schön, dich zu sehen.", "Добрый день! Рад тебя видеть.", "amused"),
        ("Da bist du ja wieder.", "А вот и ты снова.", "neutral"),
    ),
    "poke_head": (
        ("Au!", "Ай!", "surprised"),
        ("Aua, mein Kopf!", "Ой, моя голова!", "surprised"),
        ("Nicht auf den Kopf!", "Только не по голове!", "angry"),
    ),
    "dizzy": (
        ("Mir ist schwindlig.", "У меня голова кружится.", "drunk"),
        ("Alles dreht sich!", "Всё кружится!", "drunk"),
    ),
    "poke_eye": (
        ("Hey, mein Auge!", "Эй, мой глаз!", "angry"),
        ("Ich habe nur acht Augen!", "У меня всего восемь глаз!", "disgusted"),
    ),
    "poke_belly": (
        ("Hihi, das kitzelt!", "Хи-хи, щекотно!", "amused"),
        ("Uff!", "Уф!", "surprised"),
        ("Nicht drücken, ich habe gerade gegessen!", "Не дави, я только что поел!", "disgusted"),
    ),
    "poke_leg": (
        ("Autsch, mein Bein!", "Ай, моя нога!", "surprised"),
        ("Zum Glück habe ich noch sieben.", "Хорошо, что осталось ещё семь.", "amused"),
        ("Das war mein Lieblingsbein!", "Это была моя любимая нога!", "angry"),
    ),
    "pull_thread": (
        ("Hey, das ist mein Faden!", "Эй, это моя нить!", "angry"),
        ("Huiii!", "Уииии!", "amused"),
    ),
    "swing": (
        ("Huiii, schaukeln!", "Уиии, качели!", "amused"),
        ("Höher, höher!", "Выше, выше!", "amused"),
    ),
    "stroke": (
        ("Mmm, schön.", "Ммм, приятно.", "sleepy"),
        ("Mehr davon, bitte.", "Ещё, пожалуйста.", "amused"),
    ),
    "angry": (
        ("Jetzt reicht es!", "Ну всё, хватит!", "angry"),
        ("Ich gehe!", "Я ухожу!", "angry"),
    ),
    "back": (
        ("Na gut, ich bin wieder da.", "Ладно, я вернулся.", "neutral"),
        ("Ich verzeihe dir. Diesmal.", "Прощаю. На этот раз.", "neutral"),
    ),
    "fly_eat": (
        ("Mmm, lecker!", "Ммм, вкусно!", "amused"),
        ("Knusprig!", "Хрустящая!", "amused"),
        ("Die beste Fliege der Woche.", "Лучшая муха недели.", "amused"),
    ),
    "fly_full": (
        ("Ich bin satt.", "Я сыт.", "neutral"),
        ("Danke, keine Fliegen mehr.", "Спасибо, мух больше не надо.", "disgusted"),
    ),
    "cymbal": (
        ("Ah! Erschreck mich nicht!", "А! Не пугай меня!", "surprised"),
        ("Was war das?", "Что это было?", "surprised"),
    ),
    "pie": (
        ("Igitt!", "Фу!", "disgusted"),
        ("Sahne? Ich mag nur Fliegen!", "Сливки? Я люблю только мух!", "disgusted"),
    ),
    "web": (
        ("Ein Kunstwerk!", "Произведение искусства!", "amused"),
        ("Fertig. Jeder Faden sitzt.", "Готово. Каждая нить на месте.", "neutral"),
    ),
    "sleep": (
        ("Gute Nacht.", "Спокойной ночи.", "sleepy"),
        ("Ich bin müde.", "Я устал.", "sleepy"),
    ),
    "wake": (
        ("Guten Morgen!", "Доброе утро!", "amused"),
        ("Ich habe von Fliegen geträumt.", "Мне снились мухи.", "sleepy"),
    ),
    "wake_angry": (
        ("Lass mich schlafen!", "Дай поспать!", "sleepy"),
        ("Pssst, ich schlafe.", "Тссс, я сплю.", "whisper"),
    ),
    "hungry": (
        ("Ich habe Hunger.", "Я голоден.", "sleepy"),
        ("Eine Fliege wäre jetzt schön.", "Сейчас бы муху.", "neutral"),
    ),
    "tired": (
        ("Ich bin so müde.", "Я так устал.", "sleepy"),
        ("Mach doch das Licht aus.", "Выключи свет, а?", "sleepy"),
    ),
    "bored": (
        ("Mir ist langweilig.", "Мне скучно.", "neutral"),
        ("Spiel mit mir!", "Поиграй со мной!", "amused"),
    ),
    "level": (
        ("Ich bin gewachsen!", "Я подрос!", "amused"),
        ("Neues Level! Ich bin stolz auf mich.", "Новый уровень! Горжусь собой.", "amused"),
    ),
    "dress": (
        ("Steht mir gut, oder?", "Мне идёт, правда?", "amused"),
        ("Sehr elegant.", "Очень элегантно.", "neutral"),
    ),
    "read": (
        ("Ich lese dir etwas vor.", "Я тебе почитаю.", "neutral"),
    ),
}

#: мысли в облачке, без голоса: подсказки игроку
HINTS = {
    "listen": "Слушаю…",
    "mic_off": "Нажми «Говори», и я повторю.",
    "no_mic": "Микрофона нет — напиши, что сказать.",
}


def line(occasion: str, rng: random.Random | None = None, avoid: tuple[str, ...] | list[str] = ()) -> str:
    """Реплика по поводу или разделу; недавно сказанное выбирается, только если другого нет."""
    variants = LINES.get(occasion) or LINES["idle"]
    fresh = [text for text in variants if text not in set(avoid)]
    return (rng or random).choice(fresh or list(variants))


def talk_lines() -> dict[str, list[dict]]:
    """Реплики игры для страницы: {повод: [{de, ru, emotion}]}."""
    return {key: [{"de": de, "ru": ru, "emotion": emotion} for de, ru, emotion in variants]
            for key, variants in TALK.items()}


def all_talk() -> list[tuple[str, str]]:
    """Все немецкие фразы игры с манерой — чтобы заранее синтезировать их голосом Пафнутия."""
    return [(de, emotion) for variants in TALK.values() for de, _, emotion in variants]
