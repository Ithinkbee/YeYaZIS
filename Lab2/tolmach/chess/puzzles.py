"""Задачи «мат в два хода», которыми Пафнутий преграждает путь.

Позиции не сочинены вручную, а найдены перебором (`tools/find_puzzles.py`) и
отобраны по трём условиям:

    мат в два хода существует;
    мата в один хода нет — иначе задача не двухходовка;
    первый ход единственный — у задачи ровно одно решение.

Каждое условие проверяется тестами полным перебором, поэтому ошибиться в
разметке невозможно. Художественной ценности у таких позиций немного:
это честные двухходовки, а не составленные этюды.
"""

from __future__ import annotations

from dataclasses import dataclass

from .board import PIECE_NAMES, Position, square_index


@dataclass(slots=True, frozen=True)
class Puzzle:
    """Задача: позиция, решение и подсказка."""

    #: расстановка в FEN, ход белых
    fen: str
    #: единственный верный первый ход в записи вида d3g6
    key: str
    #: во сколько ходов ставится мат
    moves: int = 2

    @property
    def key_from(self) -> str:
        return self.key[:2]

    @property
    def key_to(self) -> str:
        return self.key[2:4]

    def hint(self) -> str:
        """Подсказка: какой фигурой ходить, но не куда.

        Названа фигура и её поле — этого хватает, чтобы сдвинуться с мёртвой
        точки, но решение остаётся за игроком.
        """
        position = Position.from_fen(self.fen)
        piece = position.piece_at(square_index(self.key_from))
        name = PIECE_NAMES.get(piece.lower(), "фигура")
        return f"Ходить нужно фигурой «{name}» с поля {self.key_from}."

    def solution(self) -> str:
        """Полная запись первого хода — показывается только после сдачи."""
        return f"{self.key_from}—{self.key_to}"


#: набор задач; отобран так, чтобы различались и фигуры, и идея решения
PUZZLES: tuple[Puzzle, ...] = (
    # слон уходит на дальнюю диагональ и отнимает поля у короля
    Puzzle("3k4/8/2K5/4R3/8/p2B4/8/8 w - - 0 1", "d3g6"),
    # конь отступает, освобождая ферзю линию
    Puzzle("5Nk1/4Q3/8/1p6/8/8/8/3K4 w - - 0 1", "f8e6"),
    # решает ход королём, а не тяжёлой фигурой
    Puzzle("k7/7R/5p2/2K5/8/8/8/1B6 w - - 0 1", "c5b6"),
    # снова король: он отнимает у чёрных последнее поле
    Puzzle("8/8/5B2/8/p1R4K/8/8/7k w - - 0 1", "h4g3"),
    # ферзь становится под бой, но берущего нет
    Puzzle("8/7p/8/1Q6/1R2K3/8/8/6k1 w - - 0 1", "b5e2"),
    # ферзь переходит на край доски
    Puzzle("2K2k2/5p2/4Q3/8/8/8/1R6/8 w - - 0 1", "e6h6"),
    # у чёрных восемь ответов, и все ведут к мату
    Puzzle("4Q1R1/8/8/1Kn5/8/8/2P5/5k2 w - - 0 1", "e8e3"),
    # ферзь приближается вплотную
    Puzzle("8/8/2nP4/2Q5/8/4K3/k7/7R w - - 0 1", "c5c3"),
)


def pick(index: int | None = None, rng=None) -> Puzzle:
    """Задача по номеру или случайная."""
    if index is not None:
        return PUZZLES[index % len(PUZZLES)]
    import random

    return (rng or random).choice(PUZZLES)


def index_of(puzzle: Puzzle) -> int:
    return PUZZLES.index(puzzle)


def verify(puzzle: Puzzle) -> tuple[bool, str]:
    """Проверяет задачу полным перебором.

    Возвращает пару «годна / причина отказа». Используется тестами, а не в
    работе системы: перебор занимает заметное время.
    """
    from . import engine

    position = Position.from_fen(puzzle.fen)
    if position.turn != "w":
        return False, "ход должен быть за белыми"
    if position.in_check("b"):
        return False, "чёрные уже под шахом"
    if engine.is_mate_in(position, puzzle.moves - 1):
        return False, f"мат ставится быстрее, чем за {puzzle.moves} хода"
    if not engine.is_mate_in(position, puzzle.moves):
        return False, f"мата за {puzzle.moves} хода нет"

    solutions = [move.uci() for move in engine.mating_moves(position, puzzle.moves)]
    if len(solutions) != 1:
        return False, f"решений несколько: {', '.join(sorted(solutions))}"
    if solutions[0] != puzzle.key:
        return False, f"решение {solutions[0]}, а записано {puzzle.key}"
    return True, "годна"
