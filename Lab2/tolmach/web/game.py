"""Игровая часть: шахматы с Пафнутием и викторина при взятии.

Состояния партии на сервере нет: браузер присылает позицию в FEN, сервер
проверяет ход, отвечает своим и возвращает новую позицию. Так партия
переживает перезапуск сервера, не занимает память и не требует ни сессий, ни
уборки заброшенных игр. Подделать позицию при таком устройстве можно, но
развлечение того не стоит, а распознавание языка от партии не зависит.

Правило взятия — то, ради чего всё затевалось. Когда игрок берёт фигуру,
показывается слово из обучающего корпуса, записанное латиницей. Угадал язык —
взятие состоится; ошибся — Пафнутий съедает фигуру, которой игрок ходил, и
забирает ход себе.

Ход разбит на две половины: `player_move` проверяет и выполняет ход игрока
(доли миллисекунды), `spider_move` отвечает за Пафнутия (перебор — десятые
доли секунды). Интерфейс показывает ход игрока сразу и только потом ждёт
паука; `play` выполняет обе половины разом.
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .. import config, pafnuty, quiz
from ..chess import Move, Position, best_move, puzzles, square_index, square_name

#: игрок всегда играет белыми, Пафнутий — чёрными
PLAYER = "w"
SPIDER = "b"

#: состояния, после которых ходов больше нет
FINISHED = ("checkmate", "stalemate", "draw")

#: перевес по материалу (в сотых пешки), о котором паук считает нужным сказать
MATERIAL_REMARK = 300


@dataclass(slots=True)
class MoveOutcome:
    """Результат попытки хода."""

    ok: bool
    fen: str
    message: str = ""
    #: что произошло: «move», «penalty», «illegal», «quiz», «reply»
    kind: str = "move"
    #: ход Пафнутия в ответ, если он состоялся
    reply: str = ""
    reply_line: str = ""
    #: состояние партии после всех ходов
    status: str = "ok"
    #: поля, которые стоит подсветить
    highlight: tuple[str, ...] = ()
    #: реплика Пафнутия о ходе игрока
    line: str = ""
    #: сообщение о наказании за неверный ответ, без описания состояния партии
    note: str = ""
    #: законные ходы игрока в новой позиции — для мгновенного показа хода
    legal: tuple[str, ...] = ()


def describe_status(position: Position, status: str) -> str:
    """Словесное описание состояния партии с точки зрения игрока."""
    if status == "checkmate":
        return "Мат вам — Пафнутий победил." if position.turn == PLAYER else "Мат! Пафнутий разгромлен."
    if status == "stalemate":
        return "Пат: ходов нет, но и мата нет. Ничья."
    if status == "draw":
        return "Ничья: материала для мата не осталось."
    if status == "check":
        return "Шах." if position.turn == PLAYER else "Шах Пафнутию."
    return ""


def is_capture(position: Position, move: Move) -> bool:
    """Является ли ход взятием (включая взятие на проходе)."""
    return move.en_passant or position.piece_at(move.to) != "."


def apply_penalty(position: Position, move: Move) -> tuple[Position, str]:
    """Наказание за неверный ответ: Пафнутий съедает фигуру игрока.

    Фигура снимается с доски, а ход переходит сопернику. Два случая
    оговорены отдельно:

    короля снять нельзя — иначе партия просто исчезнет, поэтому ход
    считается потерянным;

    фигуру, прикрывающую короля, снять тоже нельзя — получилась бы позиция,
    в которой король уже под боем при чужом ходе, а такой в шахматах не
    бывает. В обоих случаях игрок теряет только темп.
    """
    piece = position.piece_at(move.frm)
    after = position.copy()

    if piece.lower() == "k":
        after.turn = position.opponent(position.turn)
        return after, "Короля Пафнутий тронуть не смеет — но ход вы потеряли."

    after.squares[move.frm] = "."
    after.turn = position.opponent(position.turn)
    if after.in_check(position.turn):
        # снятие обнажило короля: откатываемся к простой потере хода
        after = position.copy()
        after.turn = position.opponent(position.turn)
        return after, "Эта фигура прикрывает короля — Пафнутий ограничился вашим ходом."

    from ..chess import PIECE_NAMES

    name = PIECE_NAMES.get(piece.lower(), "фигура")
    return after, f"Пафнутий съел вашу фигуру «{name}» с поля {square_name(move.frm)}."


def captured_piece(position: Position, move: Move) -> str:
    """Фигура, которую снимает ход; для взятия на проходе — пешка рядом."""
    if move.en_passant:
        return "p" if position.turn == PLAYER else "P"
    return position.piece_at(move.to)


def legal_moves(position: Position) -> tuple[str, ...]:
    """Законные ходы игрока — интерфейс по ним показывает ход, не дожидаясь сервера."""
    if position.turn != PLAYER or position.status() in FINISHED:
        return ()
    return tuple(move.uci() for move in position.generate_moves())


def _player_remark(
    before: Position, move: Move, after: Position, status: str,
    captured: str, rng: random.Random | None, avoid: tuple[str, ...],
) -> str:
    """Реплика Пафнутия о ходе игрока: самый заметный повод из нескольких."""
    if status == "checkmate":
        return pafnuty.line("lose", rng, avoid)
    if status in FINISHED:
        return pafnuty.line("draw", rng, avoid)

    piece = before.piece_at(move.frm)
    kind = piece.lower()
    fields = pafnuty.piece_fields(piece, square_name(move.to))
    if status == "check":
        occasion = "player_check"
    elif captured != ".":
        occasion, fields = "player_capture", pafnuty.piece_fields(captured, square_name(move.to))
    elif move.is_castling:
        occasion = "player_castle"
    elif move.promotion:
        occasion = "player_promote"
    elif kind not in ("p", "k") and after.is_attacked(move.to, SPIDER) \
            and not after.is_attacked(move.to, PLAYER):
        occasion = "player_hanging"
    elif kind == "k":
        occasion = "player_king_walk"
    elif kind == "q" and before.fullmove <= 6:
        occasion = "player_queen_early"
    elif before.fullmove <= 3:
        occasion = "player_opening"
    else:
        occasion = "player_move"
    return pafnuty.line(occasion, rng, avoid, **fields)


def _spider_remark(
    before: Position, move: Move, after: Position, status: str,
    rng: random.Random | None, avoid: tuple[str, ...],
) -> str:
    """Реплика Пафнутия о собственном ходе."""
    if status == "checkmate":
        return pafnuty.line("win", rng, avoid)
    if status in FINISHED:
        return pafnuty.line("draw", rng, avoid)

    captured = captured_piece(before, move)
    if captured != ".":
        return pafnuty.line(
            "engine_capture", rng, avoid, **pafnuty.piece_fields(captured, square_name(move.to))
        )
    if status == "check":
        return pafnuty.line("check", rng, avoid)
    if move.is_castling:
        return pafnuty.line("spider_castle", rng, avoid)
    if move.promotion:
        return pafnuty.line("spider_promote", rng, avoid)

    balance = after.material(SPIDER) - after.material(PLAYER)
    chance = (rng or random).random()
    if balance >= MATERIAL_REMARK and chance < 0.4:
        return pafnuty.line("spider_ahead", rng, avoid)
    if balance <= -MATERIAL_REMARK and chance < 0.4:
        return pafnuty.line("spider_behind", rng, avoid)
    return pafnuty.line("move", rng, avoid)


def player_move(
    fen: str,
    frm: str,
    to: str,
    promotion: str = "",
    quiz_passed: bool | None = None,
    rng: random.Random | None = None,
    avoid: tuple[str, ...] = (),
) -> MoveOutcome:
    """Ход игрока без ответа Пафнутия.

    `quiz_passed` имеет смысл только для взятия: None означает, что викторина
    ещё не пройдена и ход выполнять рано.
    """
    position = Position.from_fen(fen)
    if position.turn != PLAYER:
        return MoveOutcome(False, fen, "Сейчас ход Пафнутия.", kind="illegal")

    try:
        move = position.find_move(square_index(frm), square_index(to), promotion)
    except ValueError as problem:
        return MoveOutcome(False, fen, str(problem), kind="illegal",
                           line=pafnuty.line("illegal", rng, avoid))

    if move is None:
        return MoveOutcome(False, fen, "Так эта фигура не ходит.", kind="illegal",
                           line=pafnuty.line("illegal", rng, avoid))

    capture = is_capture(position, move)
    if capture and quiz_passed is None:
        return MoveOutcome(False, fen, "Сначала определите язык слова.", kind="quiz")

    if capture and not quiz_passed:
        after, note = apply_penalty(position, move)
        status = after.status()
        piece = position.piece_at(move.frm)
        if piece.lower() == "k":
            remark = pafnuty.line("penalty_king", rng, avoid)
        elif after.piece_at(move.frm) != ".":
            remark = pafnuty.line("penalty_pinned", rng, avoid)
        else:
            remark = pafnuty.line(
                "penalty", rng, avoid, **pafnuty.piece_fields(piece, square_name(move.frm))
            )
        return MoveOutcome(
            True, after.to_fen(),
            " ".join(filter(None, (note, describe_status(after, status)))),
            kind="penalty", status=status, highlight=(frm,), line=remark, note=note,
        )

    captured = captured_piece(position, move) if capture else "."
    after = position.make_move(move)
    status = after.status()
    return MoveOutcome(
        True, after.to_fen(), describe_status(after, status),
        kind="move", status=status, highlight=(frm, to),
        line=_player_remark(position, move, after, status, captured, rng, avoid),
    )


def spider_move(
    fen: str,
    rng: random.Random | None = None,
    avoid: tuple[str, ...] = (),
) -> MoveOutcome:
    """Ответный ход Пафнутия в позиции, где очередь чёрных."""
    position = Position.from_fen(fen)
    if position.turn != SPIDER:
        return MoveOutcome(False, fen, "Сейчас ваш ход.", kind="illegal")

    status = position.status()
    if status in FINISHED:
        return MoveOutcome(True, fen, describe_status(position, status), kind="reply", status=status)

    move = best_move(position, depth=config.CHESS_DEPTH, rng=rng)
    if move is None:
        return MoveOutcome(True, fen, "", kind="reply", status=status)

    after = position.make_move(move)
    status = after.status()
    reply = move.uci()
    return MoveOutcome(
        True, after.to_fen(), describe_status(after, status),
        kind="reply", reply=reply,
        reply_line=_spider_remark(position, move, after, status, rng, avoid),
        status=status, highlight=(reply[:2], reply[2:4]),
        legal=legal_moves(after),
    )


def spider_reply(position: Position, rng: random.Random | None = None) -> tuple[Position, str, str]:
    """Ход Пафнутия. Возвращает позицию, запись хода и реплику."""
    outcome = spider_move(position.to_fen(), rng)
    if not outcome.reply:
        return position, "", ""
    return Position.from_fen(outcome.fen), outcome.reply, outcome.reply_line


def play(
    fen: str,
    frm: str,
    to: str,
    promotion: str = "",
    quiz_passed: bool | None = None,
    rng: random.Random | None = None,
    avoid: tuple[str, ...] = (),
) -> MoveOutcome:
    """Полный ход игрока с ответом Пафнутия — обе половины разом."""
    first = player_move(fen, frm, to, promotion, quiz_passed, rng, avoid)
    if not first.ok or first.status in FINISHED:
        return first

    second = spider_move(first.fen, rng, avoid + (first.line,))
    return MoveOutcome(
        True,
        second.fen,
        " ".join(filter(None, (first.note, second.message))),
        kind=first.kind,
        reply=second.reply,
        reply_line=second.reply_line,
        status=second.status,
        highlight=first.highlight + second.highlight,
        line=first.line,
        note=first.note,
        legal=second.legal,
    )


# --- задача «мат в два хода» -------------------------------------------------


def puzzle_payload(index: int | None = None, rng: random.Random | None = None) -> dict:
    """Данные задачи для интерфейса; решение на клиент не уходит."""
    puzzle = puzzles.pick(index, rng)
    position = Position.from_fen(puzzle.fen)
    return {
        "index": puzzles.index_of(puzzle),
        "fen": puzzle.fen,
        "moves": puzzle.moves,
        "task": f"Поставьте мат чёрному королю за {puzzle.moves} хода.",
        "line": pafnuty.line("gate", rng),
        "legal": [move.uci() for move in position.generate_moves()],
    }


def try_puzzle(index: int, frm: str, to: str, promotion: str = "",
               attempts: int = 0, rng: random.Random | None = None,
               avoid: tuple[str, ...] = ()) -> dict:
    """Проверяет первый ход задачи.

    Ход сверяется не со строкой решения, а с перебором: любой ход, ведущий к
    форсированному мату, засчитывается. Для отобранных задач такой ход ровно
    один, но правило не должно зависеть от разметки.
    """
    puzzle = puzzles.pick(index)
    position = Position.from_fen(puzzle.fen)

    try:
        move = position.find_move(square_index(frm), square_index(to), promotion)
    except ValueError as problem:
        return {"solved": False, "message": str(problem), "line": pafnuty.line("gate_wrong", rng, avoid)}

    if move is None:
        return {
            "solved": False,
            "message": "Так эта фигура не ходит.",
            "line": pafnuty.line("gate_wrong", rng, avoid),
            "hint": puzzle.hint() if attempts + 1 >= config.PUZZLE_HINT_AFTER else "",
        }

    after = position.make_move(move)
    # Мат ставит тот, кто ходил: после хода белых очередь чёрных, а спрашивать
    # надо по-прежнему про белых — сохранился ли у них форсированный мат.
    solved = _leads_to_mate(after, puzzle.moves)

    if solved:
        return {
            "solved": True,
            "fen": after.to_fen(),
            "message": "Мат в два хода найден.",
            "line": pafnuty.line("gate_solved", rng, avoid),
        }

    return {
        "solved": False,
        "fen": after.to_fen(),
        "message": "Мата за два хода после этого нет.",
        "line": pafnuty.line("gate_wrong", rng, avoid),
        "hint": puzzle.hint() if attempts + 1 >= config.PUZZLE_HINT_AFTER else "",
    }


def _leads_to_mate(position: Position, moves_count: int) -> bool:
    """Сохраняется ли у игрока форсированный мат после сделанного хода."""
    from ..chess import engine

    return engine.has_forced_mate(position, PLAYER, moves_count)


# --- викторина ----------------------------------------------------------------


def quiz_payload(bank: quiz.WordBank, rng: random.Random | None = None) -> dict:
    """Вопрос викторины: слово латиницей и варианты ответа."""
    word = bank.pick(rng)
    if word is None:
        return {}
    return {
        "word": word.shown,
        "options": [
            {"code": code, "name": config.language_name(code)}
            for code in config.LANGUAGE_CODES
        ],
        "prompt": "На каком языке это слово?",
    }


def quiz_answer(bank: quiz.WordBank, shown: str, answer: str, recognizer=None,
                rng: random.Random | None = None, avoid: tuple[str, ...] = ()) -> dict:
    """Проверяет ответ игрока и показывает мнение методов системы."""
    word = bank.find(shown)
    if word is None:
        return {"known": False, "correct": False, "message": "Такого слова в паутине нет."}

    correct = answer == word.language
    opinions = quiz.system_opinion(recognizer, word)
    return {
        "known": True,
        "correct": correct,
        "word": word.shown,
        "original": word.original,
        "language": word.language,
        "language_name": word.language_name,
        "opinions": opinions,
        "opinion_summary": quiz.opinion_summary(opinions, word),
        "line": pafnuty.line("quiz_right" if correct else "quiz_wrong", rng, avoid),
    }
