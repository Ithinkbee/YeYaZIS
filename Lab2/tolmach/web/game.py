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
"""

from __future__ import annotations

import random
from dataclasses import dataclass

from .. import config, pafnuty, quiz
from ..chess import Move, Position, best_move, puzzles, square_index, square_name

#: игрок всегда играет белыми, Пафнутий — чёрными
PLAYER = "w"
SPIDER = "b"


@dataclass(slots=True)
class MoveOutcome:
    """Результат попытки хода."""

    ok: bool
    fen: str
    message: str = ""
    #: что произошло: «move», «penalty», «illegal»
    kind: str = "move"
    #: ход Пафнутия в ответ, если он состоялся
    reply: str = ""
    reply_line: str = ""
    #: состояние партии после всех ходов
    status: str = "ok"
    #: поля, которые стоит подсветить
    highlight: tuple[str, ...] = ()


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


def spider_reply(position: Position, rng: random.Random | None = None) -> tuple[Position, str, str]:
    """Ход Пафнутия. Возвращает позицию, запись хода и реплику."""
    if position.turn != SPIDER:
        return position, "", ""
    if position.status() in ("checkmate", "stalemate", "draw"):
        return position, "", ""

    move = best_move(position, depth=config.CHESS_DEPTH, rng=rng)
    if move is None:
        return position, "", ""

    captured = is_capture(position, move)
    after = position.make_move(move)
    occasion = "engine_capture" if captured else ("check" if after.in_check(PLAYER) else "move")
    return after, move.uci(), pafnuty.line(occasion, rng)


def play(
    fen: str,
    frm: str,
    to: str,
    promotion: str = "",
    quiz_passed: bool | None = None,
    rng: random.Random | None = None,
) -> MoveOutcome:
    """Полный ход игрока с ответом Пафнутия.

    `quiz_passed` имеет смысл только для взятия: None означает, что викторина
    ещё не пройдена и ход выполнять рано.
    """
    position = Position.from_fen(fen)
    if position.turn != PLAYER:
        return MoveOutcome(False, fen, "Сейчас ход Пафнутия.", kind="illegal")

    try:
        move = position.find_move(square_index(frm), square_index(to), promotion)
    except ValueError as problem:
        return MoveOutcome(False, fen, str(problem), kind="illegal")

    if move is None:
        return MoveOutcome(False, fen, "Так эта фигура не ходит.", kind="illegal")

    capture = is_capture(position, move)
    if capture and quiz_passed is None:
        return MoveOutcome(False, fen, "Сначала определите язык слова.", kind="quiz")

    if capture and not quiz_passed:
        after, message = apply_penalty(position, move)
        highlight = (frm,)
    else:
        after = position.make_move(move)
        message = ""
        highlight = (frm, to)

    status = after.status()
    if status in ("checkmate", "stalemate", "draw"):
        return MoveOutcome(
            True, after.to_fen(),
            " ".join(filter(None, (message, describe_status(after, status)))),
            kind="penalty" if (capture and not quiz_passed) else "move",
            status=status, highlight=highlight,
        )

    after, reply, reply_line = spider_reply(after, rng)
    status = after.status()
    if status in ("checkmate", "stalemate", "draw"):
        reply_line = pafnuty.line(
            {"checkmate": "win", "stalemate": "draw", "draw": "draw"}[status], rng
        )

    if reply:
        highlight = highlight + (reply[:2], reply[2:4])

    return MoveOutcome(
        True,
        after.to_fen(),
        " ".join(filter(None, (message, describe_status(after, status)))),
        kind="penalty" if (capture and not quiz_passed) else "move",
        reply=reply,
        reply_line=reply_line,
        status=status,
        highlight=highlight,
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
               attempts: int = 0, rng: random.Random | None = None) -> dict:
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
        return {"solved": False, "message": str(problem), "line": pafnuty.line("gate_wrong", rng)}

    if move is None:
        return {
            "solved": False,
            "message": "Так эта фигура не ходит.",
            "line": pafnuty.line("gate_wrong", rng),
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
            "line": pafnuty.line("gate_solved", rng),
        }

    return {
        "solved": False,
        "fen": after.to_fen(),
        "message": "Мата за два хода после этого нет.",
        "line": pafnuty.line("gate_wrong", rng),
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
                rng: random.Random | None = None) -> dict:
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
        "line": pafnuty.line("quiz_right" if correct else "quiz_wrong", rng),
    }
