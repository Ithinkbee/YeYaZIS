"""Проверка шахматного движка, задач и правила взятия.

Главная проверка здесь — perft: подсчёт числа ходов на несколько полуходов
вперёд из позиций, для которых эталонные числа общеизвестны. Она ловит почти
любую ошибку в правилах, включая взятие на проходе, рокировку через битое
поле и связанные фигуры, — по отдельности такие случаи выловить трудно.
"""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tolmach.chess import Position, START_FEN, engine, puzzles  # noqa: E402
from tolmach.chess.board import Move, square_index, square_name  # noqa: E402
from tolmach.web import game  # noqa: E402


def perft(position: Position, depth: int) -> int:
    """Число листьев дерева ходов на заданной глубине."""
    if depth == 0:
        return 1
    moves = position.generate_moves()
    if depth == 1:
        return len(moves)
    return sum(perft(position.make_move(move), depth - 1) for move in moves)


#: эталонные значения из общепринятого набора позиций для проверки движков
PERFT_CASES = [
    ("начальная", START_FEN, 1, 20),
    ("начальная", START_FEN, 2, 400),
    ("начальная", START_FEN, 3, 8902),
    ("рокировки и связки", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 1, 48),
    ("рокировки и связки", "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1", 2, 2039),
    ("взятие на проходе", "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1", 3, 2812),
    ("превращения", "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1", 2, 264),
    ("плотная позиция", "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8", 2, 1486),
]


@pytest.mark.parametrize("name,fen,depth,expected", PERFT_CASES)
def test_perft_matches_reference(name, fen, depth, expected):
    assert perft(Position.from_fen(fen), depth) == expected, name


# --- FEN и поля --------------------------------------------------------------


def test_square_names_match_fen_order():
    assert square_name(0) == "a8"
    assert square_name(7) == "h8"
    assert square_name(56) == "a1"
    assert square_name(63) == "h1"
    for square in range(64):
        assert square_index(square_name(square)) == square


def test_fen_roundtrip_preserves_everything():
    for fen in (
        START_FEN,
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 b - c6 3 12",
    ):
        assert Position.from_fen(fen).to_fen() == fen


def test_bad_fen_is_rejected():
    for bad in ("", "не фен", "8/8/8/8 w"):
        with pytest.raises(ValueError):
            Position.from_fen(bad)


def test_make_move_does_not_mutate_source():
    position = Position.from_fen(START_FEN)
    before = position.to_fen()
    position.make_move(position.generate_moves()[0])
    assert position.to_fen() == before


# --- особые ходы -------------------------------------------------------------


def test_castling_moves_the_rook():
    position = Position.from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
    move = position.find_move(square_index("e1"), square_index("g1"))
    assert move is not None and move.is_castling
    after = position.make_move(move)
    assert after.piece_at(square_index("g1")) == "K"
    assert after.piece_at(square_index("f1")) == "R"
    assert after.piece_at(square_index("h1")) == "."
    assert "K" not in after.castling and "Q" not in after.castling


def test_castling_through_attacked_square_is_forbidden():
    # ладья на f8 держит поле f1, через которое должен пройти король
    position = Position.from_fen("5r2/8/8/8/8/8/8/R3K2R w KQ - 0 1")
    assert position.find_move(square_index("e1"), square_index("g1")) is None


def test_en_passant_removes_the_right_pawn():
    position = Position.from_fen("8/8/8/3pP3/8/8/8/K6k w - d6 0 2")
    move = position.find_move(square_index("e5"), square_index("d6"))
    assert move is not None and move.en_passant
    after = position.make_move(move)
    assert after.piece_at(square_index("d6")) == "P"
    assert after.piece_at(square_index("d5")) == "."


def test_promotion_produces_the_chosen_piece():
    position = Position.from_fen("8/P7/8/8/8/8/8/K6k w - - 0 1")
    move = position.find_move(square_index("a7"), square_index("a8"), "q")
    assert move is not None
    assert position.make_move(move).piece_at(square_index("a8")) == "Q"


def test_pinned_piece_cannot_move_away():
    # конь на e2 связан ладьёй e8 и не может уйти с линии
    position = Position.from_fen("4r3/8/8/8/8/8/4N3/4K3 w - - 0 1")
    targets = {square_name(m.to) for m in position.generate_moves() if m.frm == square_index("e2")}
    assert targets == set()


# --- шах, мат, пат -----------------------------------------------------------


def test_checkmate_is_detected():
    assert Position.from_fen("R5k1/5ppp/8/8/8/8/8/6K1 b - - 0 1").status() == "checkmate"


def test_stalemate_is_detected():
    assert Position.from_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1").status() == "stalemate"


def test_insufficient_material_is_a_draw():
    assert Position.from_fen("8/8/8/4k3/8/8/8/K6B w - - 0 1").status() == "draw"


def test_engine_finds_mate_in_one():
    position = Position.from_fen("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
    assert engine.is_mate_in(position, 1)
    assert engine.best_move(position, depth=2).uci() == "a1a8"


def test_engine_returns_none_without_moves():
    assert engine.best_move(Position.from_fen("R5k1/5ppp/8/8/8/8/8/6K1 b - - 0 1")) is None


def test_engine_prefers_free_material():
    # у чёрных висит ферзь на h4, взять его нечем помешать
    position = Position.from_fen("4k3/8/8/8/7q/8/8/4K2R w - - 0 1")
    assert engine.best_move(position, depth=2).uci() == "h1h4"


# --- задачи «мат в два хода» --------------------------------------------------


@pytest.mark.parametrize("index", range(len(puzzles.PUZZLES)))
def test_every_puzzle_is_a_genuine_two_mover(index):
    """Полный перебор: мат за два есть, мата за один нет, решение одно."""
    good, reason = puzzles.verify(puzzles.PUZZLES[index])
    assert good, f"задача {index}: {reason}"


def test_puzzle_hint_names_the_right_piece():
    for puzzle in puzzles.PUZZLES:
        assert puzzle.key_from in puzzle.hint()


def test_puzzle_pick_is_stable_by_index():
    assert puzzles.pick(0) is puzzles.pick(len(puzzles.PUZZLES))


# --- игровая обвязка ----------------------------------------------------------


def test_puzzle_accepts_the_key_move():
    puzzle = puzzles.PUZZLES[0]
    result = game.try_puzzle(0, puzzle.key_from, puzzle.key_to)
    assert result["solved"] is True


def test_puzzle_rejects_other_moves():
    puzzle = puzzles.PUZZLES[0]
    position = Position.from_fen(puzzle.fen)
    wrong = [
        move for move in position.generate_moves() if move.uci() != puzzle.key
    ][0]
    result = game.try_puzzle(0, square_name(wrong.frm), square_name(wrong.to))
    assert result["solved"] is False


def test_puzzle_hint_appears_only_after_several_attempts():
    puzzle = puzzles.PUZZLES[0]
    position = Position.from_fen(puzzle.fen)
    wrong = [m for m in position.generate_moves() if m.uci() != puzzle.key][0]
    early = game.try_puzzle(0, square_name(wrong.frm), square_name(wrong.to), attempts=0)
    late = game.try_puzzle(0, square_name(wrong.frm), square_name(wrong.to), attempts=5)
    assert not early.get("hint")
    assert late.get("hint")


CAPTURE_FEN = "rnbqkbnr/ppp1pppp/8/3p4/4P3/8/PPPP1PPP/RNBQKBNR w KQkq d6 0 2"


def test_capture_waits_for_the_quiz():
    outcome = game.play(CAPTURE_FEN, "e4", "d5")
    assert not outcome.ok and outcome.kind == "quiz"


def test_correct_answer_performs_the_capture():
    outcome = game.play(CAPTURE_FEN, "e4", "d5", quiz_passed=True, rng=random.Random(1))
    assert outcome.ok and outcome.kind == "move"
    assert Position.from_fen(outcome.fen).piece_at(square_index("d5")) == "P"


def test_wrong_answer_eats_the_players_piece():
    outcome = game.play(CAPTURE_FEN, "e4", "d5", quiz_passed=False, rng=random.Random(1))
    assert outcome.ok and outcome.kind == "penalty"
    after = Position.from_fen(outcome.fen)
    assert after.piece_at(square_index("e4")) == "."   # своя фигура съедена
    assert after.piece_at(square_index("d5")) == "p"   # чужая осталась


def test_wrong_answer_passes_the_turn():
    """После наказания ход делает Пафнутий, то есть очередь возвращается игроку."""
    outcome = game.play(CAPTURE_FEN, "e4", "d5", quiz_passed=False, rng=random.Random(1))
    assert Position.from_fen(outcome.fen).turn == "w"
    assert outcome.reply


def test_king_is_never_eaten():
    position = "4k3/8/8/8/8/8/4r3/4K3 w - - 0 1"
    outcome = game.play(position, "e1", "e2", quiz_passed=False)
    assert "K" in Position.from_fen(outcome.fen).squares
    assert "Короля" in outcome.message


def test_penalty_never_leaves_the_king_in_check():
    """Снятие прикрывающей фигуры создало бы невозможную позицию."""
    # слон e2 закрывает короля e1 от ладьи e8; взятие пешки d3 ошибочно
    position = "4r3/8/8/8/8/3p4/4B3/4K3 w - - 0 1"
    outcome = game.play(position, "e2", "d3", quiz_passed=False)
    after = Position.from_fen(outcome.fen)
    assert after.piece_at(square_index("e2")) == "B"  # фигура осталась
    assert not after.in_check("w")


def test_illegal_move_is_refused():
    outcome = game.play(START_FEN, "a1", "a8")
    assert not outcome.ok and outcome.kind == "illegal"


def test_moving_out_of_turn_is_refused():
    outcome = game.play(START_FEN.replace(" w ", " b "), "e2", "e4")
    assert not outcome.ok and outcome.kind == "illegal"


def test_spider_answers_a_normal_move():
    outcome = game.play(START_FEN, "e2", "e4", rng=random.Random(3))
    assert outcome.ok
    assert outcome.reply and outcome.reply_line
    assert Position.from_fen(outcome.fen).turn == "w"


def test_game_ends_on_checkmate():
    outcome = game.play("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1", "a1", "a8", rng=random.Random(1))
    assert outcome.status == "checkmate"
    assert "Пафнутий разгромлен" in outcome.message
