"""Поиск задач «мат в два хода» для калитки Пафнутия.

Задачи не сочиняются вручную, а находятся перебором: так исключены ошибки
разметки. Расстановка берётся случайной из заданного набора фигур и проходит
три условия:

    мата в один ход нет — иначе это не двухходовка;
    форсированный мат в два хода есть при любом ответе чёрных;
    первый ход единственный — у задачи одно решение.

Найденные позиции выводятся в виде, готовом для вставки в
`tolmach/chess/puzzles.py`. Каждая из них затем ещё раз проверяется тестами
(`tests/test_chess.py::test_every_puzzle_is_a_genuine_two_mover`).

    python tools/find_puzzles.py                 — найти 8 задач
    python tools/find_puzzles.py --count 20      — больше
    python tools/find_puzzles.py --seed 1        — другая выборка
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolmach import console  # noqa: E402
from tolmach.chess import engine  # noqa: E402
from tolmach.chess.board import Position, square_index  # noqa: E402

console.setup()

#: наборы фигур: белые (с матующей стороны) и чёрные
PIECE_SETS: tuple[tuple[str, tuple[str, ...], tuple[str, ...]], ...] = (
    ("ферзь и ладья", ("K", "Q", "R"), ("k", "p")),
    ("две ладьи", ("K", "R", "R"), ("k", "p")),
    ("ферзь и конь", ("K", "Q", "N"), ("k", "p")),
    ("ферзь и слон", ("K", "Q", "B"), ("k", "r")),
    ("ладья и слон", ("K", "R", "B"), ("k", "p")),
    ("ферзь, ладья и пешка", ("K", "Q", "R", "P"), ("k", "n")),
)


def random_position(white: tuple[str, ...], black: tuple[str, ...],
                    rng: random.Random) -> Position | None:
    """Случайная расстановка; None — если она недопустима."""
    pieces = list(white) + list(black)
    squares = rng.sample(range(64), len(pieces))
    board = ["."] * 64

    for piece, square in zip(pieces, squares):
        # пешка на первой или последней горизонтали стоять не может
        if piece.lower() == "p" and square // 8 in (0, 7):
            return None
        board[square] = piece

    position = Position(board, "w", "", -1, 0, 1)
    white_king, black_king = position.king_square("w"), position.king_square("b")
    if white_king < 0 or black_king < 0:
        return None

    # короли не могут стоять вплотную
    if max(
        abs(white_king // 8 - black_king // 8),
        abs(white_king % 8 - black_king % 8),
    ) <= 1:
        return None

    # при ходе белых чёрные не могут уже стоять под шахом
    if position.in_check("b"):
        return None
    return position


def is_good_puzzle(position: Position) -> str | None:
    """Проверяет позицию; возвращает единственное решение или None."""
    if engine.is_mate_in(position, 1):
        return None
    if not engine.is_mate_in(position, 2):
        return None
    solutions = engine.mating_moves(position, 2)
    if len(solutions) != 1:
        return None
    # у чёрных должен быть выбор ответа, иначе задача вырождается
    if len(position.make_move(solutions[0]).generate_moves()) < 2:
        return None
    return solutions[0].uci()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--count", type=int, default=8, help="сколько задач найти")
    parser.add_argument("--seed", type=int, default=20260922, help="зерно выборки")
    parser.add_argument("--limit", type=int, default=400_000, help="предел перебора")
    arguments = parser.parse_args()

    rng = random.Random(arguments.seed)
    found: list[tuple[str, str, str]] = []
    seen: set[str] = set()
    tries = 0

    print(f"Поиск задач «мат в два хода» (зерно {arguments.seed})…\n")

    while len(found) < arguments.count and tries < arguments.limit:
        tries += 1
        name, white, black = PIECE_SETS[tries % len(PIECE_SETS)]
        position = random_position(white, black, rng)
        if position is None:
            continue

        fen = position.to_fen()
        if fen in seen:
            continue
        seen.add(fen)

        key = is_good_puzzle(position)
        if key is None:
            continue

        found.append((name, fen, key))
        first = position.find_move(square_index(key[:2]), square_index(key[2:4]))
        replies = len(position.make_move(first).generate_moves())
        print(f"{len(found):2}. {name:22} {fen:<44} {key}  ответов у чёрных: {replies}")

    print(f"\nперебрано расстановок: {tries}\n")
    print("Для вставки в tolmach/chess/puzzles.py:\n")
    for name, fen, key in found:
        print(f'    # {name}')
        print(f'    Puzzle("{fen}", "{key}"),')
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
