"""Пафнутий за доской: перебор с отсечениями.

Требование к силе игры здесь необычное: соперник должен быть достаточно
осмысленным, чтобы партия не выглядела насмешкой, и достаточно слабым, чтобы
его можно было обыграть между делом. Поэтому перебор неглубокий, а из
нескольких почти равных ходов выбирается случайный — так паук не повторяет
одну и ту же партию дважды.

Оценка позиции складывается из стоимости фигур и таблиц положения: конь в
центре полезнее коня в углу, пешка ближе к превращению дороже. Этого
достаточно, чтобы Пафнутий развивал фигуры и не зевал материал на один ход.
"""

from __future__ import annotations

import random

from .board import PIECE_VALUES, Move, Position

#: глубина перебора в полуходах
DEFAULT_DEPTH = 3

#: оценка мата; заведомо больше любой материальной разницы
MATE_SCORE = 1_000_000

#: ходы, уступающие лучшему не более чем на столько сотых пешки,
#: считаются равноценными и выбираются случайно
JITTER = 25

# --- таблицы положения фигур (с точки зрения белых, поле 0 — a8) -------------

_PAWN_TABLE = (
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
)

_KNIGHT_TABLE = (
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
)

_BISHOP_TABLE = (
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
)

_ROOK_TABLE = (
      0,  0,  0,  0,  0,  0,  0,  0,
      5, 10, 10, 10, 10, 10, 10,  5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
     -5,  0,  0,  0,  0,  0,  0, -5,
      0,  0,  0,  5,  5,  0,  0,  0,
)

_QUEEN_TABLE = (
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5,  5,  5,  5,  0,-10,
     -5,  0,  5,  5,  5,  5,  0, -5,
      0,  0,  5,  5,  5,  5,  0, -5,
    -10,  5,  5,  5,  5,  5,  0,-10,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
)

_KING_TABLE = (
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -10,-20,-20,-20,-20,-20,-20,-10,
     20, 20,  0,  0,  0,  0, 20, 20,
     20, 30, 10,  0,  0, 10, 30, 20,
)

_TABLES = {
    "p": _PAWN_TABLE,
    "n": _KNIGHT_TABLE,
    "b": _BISHOP_TABLE,
    "r": _ROOK_TABLE,
    "q": _QUEEN_TABLE,
    "k": _KING_TABLE,
}


def evaluate(position: Position, side: str) -> int:
    """Оценка позиции с точки зрения стороны `side`, в сотых долях пешки."""
    score = 0
    for square, piece in enumerate(position.squares):
        if piece == ".":
            continue
        kind = piece.lower()
        white = piece.isupper()
        value = PIECE_VALUES[kind]
        # таблица задана для белых; для чёрных поле зеркалится по вертикали
        table = _TABLES[kind]
        value += table[square] if white else table[(7 - square // 8) * 8 + square % 8]
        score += value if white else -value
    return score if side == "w" else -score


def _ordered_moves(position: Position) -> list[Move]:
    """Ходы со взятиями впереди — так отсечения работают заметно лучше."""
    moves = position.generate_moves()

    def priority(move: Move) -> int:
        victim = position.squares[move.to]
        if victim == ".":
            return 0
        attacker = position.squares[move.frm]
        # сначала дешёвой фигурой берём дорогую
        return PIECE_VALUES[victim.lower()] * 10 - PIECE_VALUES[attacker.lower()]

    moves.sort(key=priority, reverse=True)
    return moves


def _search(position: Position, depth: int, alpha: int, beta: int, side: str) -> int:
    """Негамакс с альфа-бета отсечениями."""
    moves = _ordered_moves(position)

    if not moves:
        if position.in_check():
            # мат тем ценнее, чем быстрее он ставится
            losing = position.turn == side
            return -MATE_SCORE - depth if losing else MATE_SCORE + depth
        return 0  # пат

    if depth == 0:
        return evaluate(position, side)

    if position.turn == side:
        best = -MATE_SCORE * 2
        for move in moves:
            best = max(best, _search(position.make_move(move), depth - 1, alpha, beta, side))
            alpha = max(alpha, best)
            if alpha >= beta:
                break
        return best

    best = MATE_SCORE * 2
    for move in moves:
        best = min(best, _search(position.make_move(move), depth - 1, alpha, beta, side))
        beta = min(beta, best)
        if alpha >= beta:
            break
    return best


def best_move(
    position: Position,
    depth: int = DEFAULT_DEPTH,
    rng: random.Random | None = None,
) -> Move | None:
    """Лучший ход для стороны, чья очередь; None — ходов нет."""
    moves = _ordered_moves(position)
    if not moves:
        return None

    side = position.turn
    scored: list[tuple[int, Move]] = []
    alpha = -MATE_SCORE * 2
    for move in moves:
        score = _search(position.make_move(move), depth - 1, alpha, MATE_SCORE * 2, side)
        scored.append((score, move))
        alpha = max(alpha, score)

    best_score = max(score for score, _ in scored)
    candidates = [move for score, move in scored if score >= best_score - JITTER]
    generator = rng or random
    return generator.choice(candidates)


def is_mate_in(position: Position, moves_count: int) -> bool:
    """Есть ли у стороны, чья очередь, форсированный мат за `moves_count` ходов.

    Полный перебор без отсечений: используется для проверки задач, а не в
    партии, поэтому скорость здесь второстепенна, а точность обязательна.
    """
    return _forced_mate(position, position.turn, moves_count)


def has_forced_mate(position: Position, side: str, moves_count: int) -> bool:
    """Остался ли у стороны `side` форсированный мат в данной позиции.

    Отличается от `is_mate_in` тем, что сторона задаётся явно: после хода
    белых очередь чёрных, а спрашивать надо по-прежнему про белых.
    """
    return _forced_mate(position, side, moves_count)


def _forced_mate(position: Position, side: str, moves_left: int) -> bool:
    status = position.status()
    if status == "checkmate":
        # мат уже стоит: он в пользу того, чья сейчас НЕ очередь
        return position.turn != side
    if moves_left <= 0 or status in ("stalemate", "draw"):
        return False

    if position.turn == side:
        # достаточно одного хода, ведущего к мату
        return any(
            _forced_mate(position.make_move(move), side, moves_left)
            for move in position.generate_moves()
        )

    # у защищающейся стороны все ответы должны вести к мату
    replies = position.generate_moves()
    if not replies:
        return False
    return all(
        _forced_mate(position.make_move(move), side, moves_left - 1) for move in replies
    )


def mating_moves(position: Position, moves_count: int) -> list[Move]:
    """Первые ходы, ведущие к форсированному мату за `moves_count` ходов.

    Если список состоит из одного хода, задача имеет единственное решение —
    именно такие и годятся в головоломки.
    """
    side = position.turn
    return [
        move
        for move in position.generate_moves()
        if _forced_mate(position.make_move(move), side, moves_count)
    ]
