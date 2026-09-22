"""Шахматы: правила, соперник Пафнутий и задачи «мат в два хода».

Движок вынесен в отдельный подпакет и ничего не знает ни о распознавании
языка, ни о вебе: он оперирует только позициями и ходами. Связь с остальной
системой — в `tolmach/web/app.py`, где взятие фигуры превращается в вопрос
викторины.
"""

from __future__ import annotations

from .board import PIECE_NAMES, PIECE_VALUES, START_FEN, Move, Position, square_index, square_name
from .engine import best_move, evaluate, is_mate_in, mating_moves
from .puzzles import PUZZLES, Puzzle, pick, verify

__all__ = [
    "PIECE_NAMES",
    "PIECE_VALUES",
    "PUZZLES",
    "START_FEN",
    "Move",
    "Position",
    "Puzzle",
    "best_move",
    "evaluate",
    "is_mate_in",
    "mating_moves",
    "pick",
    "square_index",
    "square_name",
    "verify",
]
