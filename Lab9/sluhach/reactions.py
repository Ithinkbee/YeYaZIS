"""Реакция системы на распознанную фразу.

Фраза проходит три проверки по порядку:

1. ключевая фраза-пасхалка — звучит заготовленный ответ;
2. одна из заданных операций — система выполняет её и сообщает результат;
3. ничего из этого — система повторяет услышанное вслух.

Во время диктовки порядок другой: фраза либо управляет диктовкой («конец
диктовки», «удали последнюю фразу»), либо дописывается в текст сочинения —
молча, чтобы ответ системы не перебивал диктующего.

Результат — `Reaction`: что сказать голосом, что показать в облачке
Пафнутия, какая операция выполнена и что изменить на странице. Состояние
разговора (язык, открытое сочинение, текущий абзац, черновик диктовки) хранит
страница и присылает с каждой фразой; сервер от запроса к запросу ничего не
помнит, поэтому реакция — обычная функция от фразы и состояния.
"""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Callable

from sluhach import config, dictation, matcher, messages
from sluhach.dictation import DictationError, Dictations, Lexicon
from sluhach.eggs import EggStore
from sluhach.essays import Collection, Essay
from sluhach.operations import Operation, OperationSet
from sluhach.text import guess_number, normalize, parse_number, tokens

#: операции, примеры которых Пафнутий называет в ответ на «что ты умеешь»
HELP_EXAMPLES = ("list", "open", "read", "next", "find")
#: по этим началам слов узнаётся язык в команде «говори по-немецки»
LANGUAGE_STEMS = {"de": ("нем", "герман", "deutsch", "german"), "ru": ("рус", "russ")}
#: слова рядом с номером сочинения, которые номером не являются
NUMBER_COMPANY = {"ru": {"сочинение", "сочинения", "номер", "номером"}, "de": {"aufsatz", "nummer", "den", "das"}}
#: слова, которые в просьбе «найди слово …» искомым словом не являются
FIND_COMPANY = {"ru": {"слово", "слова", "слову", "словом"}, "de": {"das", "wort", "woerter", "dem"}}
#: звуки, которые распознаватель слышит во вздохах и шуме: фразой они не
#: считаются, и повторять их вслух незачем
HESITATIONS = frozenset({"hm", "hmm", "mhm", "aeh", "aehm", "oh", "ah", "ach", "э", "м", "мм", "эм", "а", "и",
                         "ну", "угу"})
#: операции, которые страница вызывает кнопкой, без фразы
ACTIONS = frozenset({"dictate", "dictate_undo", "dictate_end"})


@dataclass
class Draft:
    """Черновик диктовки: текст, который пишется под голос."""

    text: str = ""
    title: str = ""                # название; пустое — по первым словам текста
    essay: str = ""                # какое надиктованное сочинение правится; пусто — пишется новое
    period: bool = True            # ставить ли точку после каждой фразы
    #: как стереть последние фразы: пары (длина общего начала, что было после него), см. dictation.difference
    undo: list[list] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> "Draft | None":
        if not isinstance(data, dict):
            return None
        draft = cls(text=str(data.get("text") or "")[:config.MAX_DRAFT_CHARS],
                    title=" ".join(str(data.get("title") or "").split())[:config.MAX_TITLE_CHARS],
                    essay=str(data.get("essay") or "")[:40], period=bool(data.get("period", True)))
        steps = data.get("undo")
        for step in (steps if isinstance(steps, list) else [])[-config.DRAFT_UNDO:]:
            # шаг, который не подходит к тексту (его правили руками), отбрасывается вместе с прежними
            if (isinstance(step, list) and len(step) == 2 and isinstance(step[0], int) and isinstance(step[1], str)
                    and 0 <= step[0] <= len(draft.text) and len(step[1]) <= 8):
                draft.undo.append([step[0], step[1]])
            else:
                draft.undo = []
        return draft


@dataclass
class Session:
    """Состояние разговора; хранится на странице."""

    language: str = config.DEFAULT_LANGUAGE
    essay: str = ""                # идентификатор открытого сочинения
    paragraph: int = 0             # номер текущего абзаца, с нуля
    last_reply: str = ""           # последний ответ — для операции «повтори»
    last_language: str = ""
    draft: Draft | None = None     # черновик диктовки; None — диктовка не идёт

    @classmethod
    def from_dict(cls, data: dict | None, collection: Collection) -> "Session":
        """Состояние из запроса; всё, чему нельзя верить, заменяется исходным."""
        data = data if isinstance(data, dict) else {}
        language = data.get("language")
        session = cls(language=language if language in config.LANGUAGES else config.DEFAULT_LANGUAGE)
        essay = collection.get(str(data.get("essay") or ""))
        if essay is not None and essay.language == session.language:
            session.essay = essay.id
            try:
                session.paragraph = max(0, min(len(essay.paragraphs) - 1, int(data.get("paragraph") or 0)))
            except (TypeError, ValueError):
                session.paragraph = 0
        reply = data.get("last_reply")
        if isinstance(reply, str):
            session.last_reply = reply[:4000]
            last = data.get("last_language")
            session.last_language = last if last in config.LANGUAGES else session.language
        session.draft = Draft.from_dict(data.get("draft"))
        if session.draft is not None:
            # править можно только надиктованное сочинение на языке разговора
            target = collection.get(session.draft.essay)
            if target is None or not target.dictated or target.language != session.language:
                session.draft.essay = ""
        return session

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Reaction:
    kind: str                          # operation | egg | echo | dictation | noise | silence
    heard: str                         # распознанная фраза
    speech: str = ""                   # что система произносит
    speech_language: str = ""          # каким голосом
    display: str = ""                  # что показывает Пафнутий
    gloss: str = ""                    # тот же ответ по-русски, если он звучит не по-русски
    operation: str = ""
    title: str = ""
    phrase: str = ""                   # сработавшая фраза-шаблон
    score: float | None = None         # сходство услышанного с ней
    slot: str = ""                     # параметр, как он услышан
    near: list[dict] = field(default_factory=list)       # ближайшие операции, если ни одна не подошла
    effects: list[dict] = field(default_factory=list)    # что изменить на странице
    session: dict = field(default_factory=dict)
    ms: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class _Reply:
    """Ответ операции до перевода в слова."""

    key: str = ""
    fields: dict = field(default_factory=dict)
    russian: dict = field(default_factory=dict)       # поля, которые в русском пересказе другие
    effects: list[dict] = field(default_factory=list)
    language: str = ""                                # язык ответа, если не язык разговора
    speech: str = ""                                  # готовый текст вместо шаблона
    display: str = ""
    gloss: str = ""
    remember: bool = True                             # запоминать ли ответ для «повтори»
    silent: bool = False                              # ответ только показывается: голос перебил бы диктовку


@dataclass
class _Context:
    session: Session
    essay: Essay | None
    slot: tuple[str, ...]
    raw: tuple[str, ...]
    now: datetime


class Reactor:
    """Ядро системы: фраза и состояние разговора -> реакция."""

    def __init__(self, collection: Collection, operations: OperationSet, eggs: EggStore,
                 dictations: Dictations | None = None, lexicon: Lexicon | None = None) -> None:
        self.collection = collection
        self.operations = operations
        self.eggs = eggs
        #: куда сохраняются надиктованные сочинения; без хранилища диктовка идёт, но не сохраняется
        self.dictations = dictations
        self.lexicon = lexicon
        self._handlers: dict[str, Callable[[_Context], _Reply]] = {
            "list": self._list, "open": self._open, "next_essay": self._next_essay, "prev_essay": self._prev_essay,
            "close": self._close, "read": self._read, "next": self._next, "back": self._back, "start": self._start,
            "goto": self._goto, "info": self._info, "count": self._count, "find": self._find, "where": self._where,
            "help": self._help, "language": self._language, "repeat": self._repeat, "time": self._time,
            "stop": self._stop, "sleep": self._sleep, "game": self._game,
            "dictate": self._dictate, "dictate_undo": self._dictate_undo, "dictate_end": self._dictate_end,
        }

    def react(self, text: str, session: Session, now: datetime | None = None, action: str = "") -> Reaction:
        """Реакция на фразу; `action` — операция, вызванная кнопкой страницы, без фразы."""
        started = time.perf_counter()
        limit = config.MAX_DICTATED_PHRASE_CHARS if session.draft is not None else config.MAX_PHRASE_CHARS
        heard = " ".join((text or "").split())[:limit]
        now = now or datetime.now()
        if action in ACTIONS and self.operations.entry(action) is not None:
            reaction = self._perform(self.operations.entry(action).operation, session, now)
        elif session.draft is not None:
            reaction = self._dictation(heard, session, now)
        else:
            reaction = self._react(heard, session, now)
        reaction.session = session.to_dict()
        reaction.ms = round((time.perf_counter() - started) * 1000, 2)
        return reaction

    def _perform(self, operation: Operation, session: Session, now: datetime, heard: str = "") -> Reaction:
        """Выполняет операцию без параметра и переводит её ответ в слова."""
        context = _Context(session, self.collection.get(session.essay), (), (), now)
        reaction = self._voice(self._handlers[operation.id](context), session, heard)
        reaction.operation, reaction.title = operation.id, operation.title
        return reaction

    def _dictation(self, heard: str, session: Session, now: datetime) -> Reaction:
        """Идёт диктовка: фраза управляет ею или дописывается в текст."""
        if not normalize(heard):
            return Reaction("silence", heard)
        found = matcher.match(heard, session.language, self.operations, dictation=True)
        if found is not None:
            reaction = self._perform(found.operation, session, now, heard)
            reaction.phrase, reaction.score = found.template.text, round(found.score, 3)
            return reaction
        words = tokens(heard)
        if all(word in HESITATIONS for word in words) or (len(words) == 1 and len(words[0]) <= 2):
            return Reaction("noise", heard)

        draft = session.draft
        text = dictation.write(draft.text, heard, session.language, self.lexicon, draft.period)
        if len(text) > config.MAX_DRAFT_CHARS:
            return self._voice(_Reply("dictate_full", remember=False), session, heard)
        common, removed = dictation.difference(draft.text, text)
        draft.undo = [*draft.undo, [common, removed]][-config.DRAFT_UNDO:]
        draft.text = text
        # записанное не произносится: система молчит, пока ей диктуют
        return Reaction("dictation", heard, display=text[common:].strip(), speech_language=session.language)

    def _react(self, heard: str, session: Session, now: datetime) -> Reaction:
        if not normalize(heard):
            return Reaction("silence", heard)

        egg = self.eggs.match(heard, session.language)
        if egg is not None:
            found, score = egg
            session.last_reply, session.last_language = found.answer, found.answer_language
            return Reaction("egg", heard, speech=found.answer, speech_language=found.answer_language,
                            display=found.answer, phrase=found.key, score=round(score, 3))

        nearest = matcher.candidates(heard, session.language, self.operations)
        found = matcher.match(heard, session.language, self.operations, nearest=nearest)
        if found is not None:
            operation = found.operation
            essay = self.collection.get(session.essay)
            context = _Context(session, essay, found.slot, found.raw, now)
            if operation.needs_essay and essay is None:
                reply = _Reply("need_essay")
            else:
                reply = self._handlers[operation.id](context)
            reaction = self._voice(reply, session, heard)
            reaction.kind = "operation"
            reaction.operation, reaction.title = operation.id, operation.title
            reaction.phrase, reaction.score = found.template.text, round(found.score, 3)
            reaction.slot = " ".join(found.raw)
            return reaction

        words = tokens(heard)
        if all(word in HESITATIONS for word in words) or (len(words) == 1 and len(words[0]) <= 2):
            return Reaction("noise", heard)

        reaction = self._voice(_Reply("echo", {"phrase": heard}), session, heard)
        reaction.kind = "echo"
        reaction.near = [{"title": item.operation.title, "phrase": item.template.text, "score": round(item.score, 3)}
                         for item in nearest[:2] if item.score > 0]
        return reaction

    def _voice(self, reply: _Reply, session: Session, heard: str) -> Reaction:
        """Переводит ответ операции в слова на языке разговора."""
        language = reply.language or session.language
        speech = reply.speech or messages.render(reply.key, language, **reply.fields)
        display = reply.display or speech
        gloss = reply.gloss
        if not gloss and language != "ru" and reply.key:
            gloss = messages.render(reply.key, "ru", **{**reply.fields, **reply.russian})
        if reply.silent:
            speech = ""
        elif reply.remember:
            session.last_reply, session.last_language = speech, language
        return Reaction("operation", heard, speech=speech, speech_language=language, display=display,
                        gloss=gloss, effects=reply.effects)

    # --- сочинения ------------------------------------------------------------------

    def _list(self, c: _Context) -> _Reply:
        language = c.session.language
        essays = self.collection.by_language(language)
        c.session.essay, c.session.paragraph = "", 0
        if not essays:
            return _Reply("list_empty")

        def titles(code: str) -> str:
            return " ".join(messages.render("list_item", code, number=i, title=essay.title)
                            for i, essay in enumerate(essays, start=1))

        return _Reply("list", {"count": len(essays), "titles": titles(language)}, {"titles": titles("ru")})

    def _opened(self, c: _Context, essay: Essay) -> _Reply:
        c.session.essay, c.session.paragraph = essay.id, 0
        return _Reply("open", {"title": essay.title, "about": essay.about, "paragraphs": essay.stats.paragraphs},
                      {"about": essay.about_ru})

    def _open(self, c: _Context) -> _Reply:
        language = c.session.language
        company = NUMBER_COMPANY.get(language, set())
        names = [word for word in c.slot if word not in company]
        number = parse_number(names, language)
        only_number = number is not None and all(parse_number([word], language) is not None for word in names)
        essay = None if only_number else self.collection.lookup(c.slot, language)
        if essay is None and number is None:
            # ни названия, ни числа: возможно, числительное расслышано с ошибкой
            number = guess_number(names, language)
        if essay is None and number is not None:
            essay = self.collection.by_number(language, number)
            if essay is None:
                return _Reply("open_number", {"number": number, "count": len(self.collection.by_language(language))})
        if essay is None:
            return _Reply("open_unknown", {"query": " ".join(c.raw)})
        return self._opened(c, essay)

    def _next_essay(self, c: _Context) -> _Reply:
        essay = self.collection.neighbour(c.essay, +1)
        return self._opened(c, essay) if essay else _Reply("essay_last")

    def _prev_essay(self, c: _Context) -> _Reply:
        essay = self.collection.neighbour(c.essay, -1)
        return self._opened(c, essay) if essay else _Reply("essay_first")

    def _close(self, c: _Context) -> _Reply:
        if c.essay is None:
            return _Reply("close_nothing")
        c.session.essay, c.session.paragraph = "", 0
        return _Reply("close")

    # --- чтение вслух -----------------------------------------------------------------

    def _read_at(self, c: _Context, index: int) -> _Reply:
        language = c.session.language
        paragraph = c.essay.paragraphs[index]
        c.session.paragraph = index
        fields = {"number": index + 1, "count": len(c.essay.paragraphs), "preview": _preview(paragraph.text)}
        speech = paragraph.text
        if paragraph.opens_section and paragraph.section:
            speech = messages.render("read_section", language, section=paragraph.section) + " " + speech
        return _Reply(speech=speech, display=messages.render("read_display", language, **fields),
                      gloss="" if language == "ru" else messages.render("read_gloss", "ru", **fields),
                      effects=[{"type": "read", "index": index}])

    def _read(self, c: _Context) -> _Reply:
        return self._read_at(c, c.session.paragraph)

    def _next(self, c: _Context) -> _Reply:
        if c.session.paragraph + 1 >= len(c.essay.paragraphs):
            return _Reply("paragraph_last")
        return self._read_at(c, c.session.paragraph + 1)

    def _back(self, c: _Context) -> _Reply:
        if c.session.paragraph <= 0:
            return _Reply("paragraph_first")
        return self._read_at(c, c.session.paragraph - 1)

    def _start(self, c: _Context) -> _Reply:
        return self._read_at(c, 0)

    def _goto(self, c: _Context) -> _Reply:
        number = guess_number(c.slot, c.session.language)
        if number is None:
            return _Reply("goto_unknown")
        count = len(c.essay.paragraphs)
        if not 1 <= number <= count:
            return _Reply("goto_missing", {"number": number, "count": count})
        return self._read_at(c, number - 1)

    # --- разбор сочинения ---------------------------------------------------------------

    def _volume(self, essay: Essay) -> dict:
        stats = essay.stats
        return {"words": stats.words, "sentences": stats.sentences, "paragraphs": stats.paragraphs}

    def _info(self, c: _Context) -> _Reply:
        return _Reply("info", {"title": c.essay.title, "about": c.essay.about, **self._volume(c.essay)},
                      {"about": c.essay.about_ru})

    def _count(self, c: _Context) -> _Reply:
        return _Reply("count", self._volume(c.essay))

    def _find(self, c: _Context) -> _Reply:
        # ищется одно слово: первое достаточно длинное, чтобы не оказаться предлогом.
        # Само слово «слово» пропускается: «найди слова романа» — это «найди слово „романа“»,
        # расслышанное с ошибкой
        company = FIND_COMPANY.get(c.session.language, set())
        pick = next((i for i, word in enumerate(c.slot) if len(word) >= 3 and word not in company),
                    next((i for i, word in enumerate(c.slot) if len(word) >= 3), 0))
        word, shown = c.slot[pick], c.raw[pick] if pick < len(c.raw) else c.slot[pick]
        found = c.essay.find(word)
        if not found.count:
            return _Reply("find_none", {"word": shown}, effects=[{"type": "highlight", "forms": []}])
        # в ответе слово пишется как в тексте: „Räuber“, а не услышанное „räuber“
        shown = next((form for form in found.forms if normalize(form) == word), shown)
        c.session.paragraph = found.nearest(c.session.paragraph)
        return _Reply("find", {"word": shown, "count": found.count, "number": c.session.paragraph + 1},
                      effects=[{"type": "highlight", "forms": list(found.forms), "word": shown}])

    def _where(self, c: _Context) -> _Reply:
        if c.essay is None:
            return _Reply("where_list")
        return _Reply("where", {"title": c.essay.title, "number": c.session.paragraph + 1,
                                "count": len(c.essay.paragraphs)})

    # --- диктовка -----------------------------------------------------------------------

    def _essays(self, language: str) -> dict:
        """Перемена для страницы: список сочинений языка стал другим."""
        return {"type": "essays", "language": language,
                "items": [essay.summary() for essay in self.collection.by_language(language)]}

    def _dictate(self, c: _Context) -> _Reply:
        if c.session.draft is None:
            c.session.draft = Draft()
            c.session.essay, c.session.paragraph = "", 0
        language = c.session.language
        hint = messages.render("dictate_hint", language, end=self.operations.example("dictate_end", language))
        return _Reply(speech=messages.render("dictate", language), display=hint, remember=False,
                      gloss="" if language == "ru" else messages.render(
                          "dictate_hint", "ru", end=self.operations.example("dictate_end", "ru")))

    def _dictate_undo(self, c: _Context) -> _Reply:
        draft = c.session.draft
        if draft is None:
            return _Reply("dictate_none", remember=False)
        if not draft.undo:
            return _Reply("dictate_undo_nothing", silent=True)
        common, removed = draft.undo.pop()
        erased = draft.text[common:].strip()
        draft.text = draft.text[:common] + removed
        return _Reply("dictate_undo", {"piece": erased}, silent=True)

    def _dictate_end(self, c: _Context) -> _Reply:
        draft, language = c.session.draft, c.session.language
        if draft is None:
            return _Reply("dictate_none", remember=False)
        if not dictation.clean(draft.text):
            c.session.draft = None
            return _Reply("dictate_empty", remember=False)
        if self.dictations is None:
            c.session.draft = None
            return _Reply("dictate_closed", remember=False)
        try:
            essay = self.dictations.save(language, draft.title, draft.text, draft.essay, c.now)
        except DictationError as problem:
            # черновик остаётся: его ещё можно поправить или сохранить, освободив место
            return _Reply("dictate_" + problem.code, problem.fields, remember=False)
        c.session.draft = None
        c.session.essay, c.session.paragraph = essay.id, 0
        return _Reply("dictate_saved", {"title": essay.title, "words": essay.stats.words,
                                        "paragraphs": essay.stats.paragraphs}, effects=[self._essays(language)])

    # --- система ------------------------------------------------------------------------

    def _help(self, c: _Context) -> _Reply:
        def examples(code: str) -> str:
            quote = "„{}“" if code == "de" else "«{}»"
            found = [self.operations.example(operation, code) for operation in HELP_EXAMPLES]
            return ", ".join(quote.format(text) for text in found if text)

        return _Reply("help", {"examples": examples(c.session.language)}, effects=[{"type": "cheatsheet"}])

    def _language(self, c: _Context) -> _Reply:
        target = next((code for word in c.slot for code, stems in LANGUAGE_STEMS.items()
                       if word.startswith(stems)), None)
        if target is None:
            return _Reply("language_unknown")
        if target == c.session.language:
            return _Reply("language_same")
        c.session.language, c.session.essay, c.session.paragraph = target, "", 0
        return _Reply("language", language=target, effects=[{"type": "language", "code": target}])

    def _repeat(self, c: _Context) -> _Reply:
        if not c.session.last_reply:
            return _Reply("repeat_nothing", remember=False)
        return _Reply(speech=c.session.last_reply, language=c.session.last_language or c.session.language,
                      remember=False)

    def _time(self, c: _Context) -> _Reply:
        return _Reply("time", {"hour": c.now.hour, "minute": c.now.minute})

    def _stop(self, c: _Context) -> _Reply:
        return _Reply("stop", effects=[{"type": "silence"}], remember=False)

    def _sleep(self, c: _Context) -> _Reply:
        return _Reply("sleep", effects=[{"type": "sleep"}], remember=False)

    def _game(self, c: _Context) -> _Reply:
        return _Reply("game", effects=[{"type": "navigate", "url": "/walk"}], remember=False)


def _preview(text: str) -> str:
    """Начало абзаца для облачка: до границы слова, с многоточием."""
    limit = config.READ_PREVIEW_CHARS
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:—– ") + "…"
