"""Правила шахмат: позиция, генерация ходов, шах, мат и пат.

Движок написан на Python, а не на JavaScript, по одной причине: задачи
«мат в два хода» должны проверяться тестами. Позиция, объявленная задачей,
обязана действительно иметь форсированный мат и не иметь мата в один ход —
проверить это можно только полным перебором, и держать такой перебор рядом с
самими задачами надёжнее, чем доверять разметке вручную.

Нумерация полей: 0 — a8, 7 — h8, 56 — a1, 63 — h1, то есть в том же порядке,
в каком поля перечисляются в FEN. Внутри генератора ходов используются пары
(ряд, столбец): арифметика по индексу поля легко «заворачивается» через край
доски, и на этом ломается генерация ходов коня и короля.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: начальная расстановка
START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

#: стоимость фигур в сотых долях пешки — для оценки позиции
PIECE_VALUES = {"p": 100, "n": 320, "b": 330, "r": 500, "q": 900, "k": 20000}

#: названия фигур для реплик и подсказок
PIECE_NAMES = {
    "p": "пешка", "n": "конь", "b": "слон",
    "r": "ладья", "q": "ферзь", "k": "король",
}

FILES = "abcdefgh"
RANKS = "87654321"


def square_name(square: int) -> str:
    """Поле в алгебраической записи: 0 -> a8, 63 -> h1."""
    return f"{FILES[square % 8]}{RANKS[square // 8]}"


def square_index(name: str) -> int:
    """Поле по алгебраической записи: a8 -> 0, h1 -> 63."""
    name = name.strip().lower()
    if len(name) != 2 or name[0] not in FILES or name[1] not in RANKS:
        raise ValueError(f"некорректное поле: {name!r}")
    return RANKS.index(name[1]) * 8 + FILES.index(name[0])


@dataclass(slots=True, frozen=True)
class Move:
    """Ход: откуда, куда и во что превращается пешка."""

    frm: int
    to: int
    promotion: str = ""

    #: взятие на проходе
    en_passant: bool = False
    #: рокировка: поля ладьи
    rook_frm: int = -1
    rook_to: int = -1

    @property
    def is_castling(self) -> bool:
        return self.rook_frm >= 0

    def uci(self) -> str:
        """Запись хода: e2e4, e7e8q."""
        return f"{square_name(self.frm)}{square_name(self.to)}{self.promotion}"

    @classmethod
    def from_uci(cls, text: str) -> Move:
        """Разбирает запись вида e2e4 или e7e8q (без флагов)."""
        text = text.strip().lower()
        if len(text) not in (4, 5):
            raise ValueError(f"некорректный ход: {text!r}")
        promotion = text[4] if len(text) == 5 else ""
        if promotion and promotion not in "qrbn":
            raise ValueError(f"некорректное превращение: {promotion!r}")
        return cls(square_index(text[:2]), square_index(text[2:4]), promotion)


#: смещения (ряд, столбец) для фигур, ходящих на фиксированное расстояние
KNIGHT_STEPS = ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1))
KING_STEPS = ((-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1))

#: направления для скользящих фигур
BISHOP_DIRS = ((-1, -1), (-1, 1), (1, -1), (1, 1))
ROOK_DIRS = ((-1, 0), (1, 0), (0, -1), (0, 1))
QUEEN_DIRS = BISHOP_DIRS + ROOK_DIRS


@dataclass(slots=True)
class Position:
    """Шахматная позиция целиком.

    Фигуры хранятся строкой из 64 символов: заглавные — белые, строчные —
    чёрные, точка — пустое поле.
    """

    squares: list[str] = field(default_factory=lambda: ["."] * 64)
    turn: str = "w"
    #: права на рокировку в обозначениях FEN, например «KQkq»
    castling: str = "KQkq"
    #: поле взятия на проходе или -1
    ep: int = -1
    halfmove: int = 0
    fullmove: int = 1

    # --- FEN -----------------------------------------------------------------

    @classmethod
    def from_fen(cls, fen: str) -> Position:
        """Разбирает позицию из FEN."""
        parts = fen.strip().split()
        if len(parts) < 4:
            raise ValueError(f"некорректный FEN: {fen!r}")

        squares: list[str] = []
        for row in parts[0].split("/"):
            for char in row:
                if char.isdigit():
                    squares.extend("." * int(char))
                else:
                    squares.append(char)
        if len(squares) != 64:
            raise ValueError(f"в FEN {len(squares)} полей вместо 64")

        turn = parts[1]
        if turn not in ("w", "b"):
            raise ValueError(f"некорректная очередь хода: {turn!r}")

        castling = "" if parts[2] == "-" else parts[2]
        ep = -1 if parts[3] == "-" else square_index(parts[3])
        halfmove = int(parts[4]) if len(parts) > 4 and parts[4].isdigit() else 0
        fullmove = int(parts[5]) if len(parts) > 5 and parts[5].isdigit() else 1

        return cls(squares, turn, castling, ep, halfmove, fullmove)

    def to_fen(self) -> str:
        """Собирает FEN текущей позиции."""
        rows: list[str] = []
        for rank in range(8):
            row, empty = "", 0
            for file in range(8):
                piece = self.squares[rank * 8 + file]
                if piece == ".":
                    empty += 1
                    continue
                if empty:
                    row += str(empty)
                    empty = 0
                row += piece
            if empty:
                row += str(empty)
            rows.append(row)
        return " ".join(
            (
                "/".join(rows),
                self.turn,
                self.castling or "-",
                square_name(self.ep) if self.ep >= 0 else "-",
                str(self.halfmove),
                str(self.fullmove),
            )
        )

    def copy(self) -> Position:
        return Position(
            list(self.squares), self.turn, self.castling, self.ep, self.halfmove, self.fullmove
        )

    # --- вспомогательное -----------------------------------------------------

    @staticmethod
    def colour_of(piece: str) -> str:
        """Цвет фигуры: «w», «b» или пустая строка для пустого поля."""
        if piece == ".":
            return ""
        return "w" if piece.isupper() else "b"

    def piece_at(self, square: int) -> str:
        return self.squares[square]

    def king_square(self, side: str) -> int:
        """Поле короля; -1, если короля на доске нет."""
        king = "K" if side == "w" else "k"
        try:
            return self.squares.index(king)
        except ValueError:
            return -1

    @staticmethod
    def opponent(side: str) -> str:
        return "b" if side == "w" else "w"

    def pieces_of(self, side: str) -> list[tuple[int, str]]:
        """Все фигуры стороны: пары (поле, символ)."""
        return [
            (square, piece)
            for square, piece in enumerate(self.squares)
            if piece != "." and self.colour_of(piece) == side
        ]

    # --- атаки ---------------------------------------------------------------

    def is_attacked(self, square: int, by: str) -> bool:
        """Атаковано ли поле стороной `by`.

        Проверка идёт «от поля наружу»: так дешевле, чем генерировать все ходы
        противника, а для определения шаха этого достаточно.
        """
        rank, file = divmod(square, 8)
        upper = by == "w"

        def at(r: int, f: int) -> str:
            return self.squares[r * 8 + f] if 0 <= r < 8 and 0 <= f < 8 else ""

        def mine(piece: str, kinds: str) -> bool:
            if not piece or piece == ".":
                return False
            return piece.isupper() == upper and piece.lower() in kinds

        # пешки: бьют по диагонали навстречу своему движению
        pawn_rank = rank + (1 if upper else -1)
        for pawn_file in (file - 1, file + 1):
            if mine(at(pawn_rank, pawn_file), "p"):
                return True

        for delta_rank, delta_file in KNIGHT_STEPS:
            if mine(at(rank + delta_rank, file + delta_file), "n"):
                return True

        for delta_rank, delta_file in KING_STEPS:
            if mine(at(rank + delta_rank, file + delta_file), "k"):
                return True

        for dirs, kinds in ((BISHOP_DIRS, "bq"), (ROOK_DIRS, "rq")):
            for delta_rank, delta_file in dirs:
                r, f = rank + delta_rank, file + delta_file
                while 0 <= r < 8 and 0 <= f < 8:
                    piece = self.squares[r * 8 + f]
                    if piece != ".":
                        if mine(piece, kinds):
                            return True
                        break
                    r += delta_rank
                    f += delta_file
        return False

    def in_check(self, side: str | None = None) -> bool:
        """Находится ли сторона под шахом."""
        side = side or self.turn
        king = self.king_square(side)
        if king < 0:
            return False
        return self.is_attacked(king, self.opponent(side))

    # --- генерация ходов -----------------------------------------------------

    def generate_moves(self) -> list[Move]:
        """Все законные ходы стороны, чья очередь.

        Сначала строятся псевдозаконные ходы, затем отбрасываются те, после
        которых собственный король остаётся под боем.
        """
        legal: list[Move] = []
        for move in self._pseudo_moves():
            after = self.make_move(move)
            if not after.in_check(self.turn):
                legal.append(move)
        return legal

    def _pseudo_moves(self) -> list[Move]:
        """Ходы без проверки на собственный шах."""
        moves: list[Move] = []
        side = self.turn
        upper = side == "w"

        for square, piece in self.pieces_of(side):
            rank, file = divmod(square, 8)
            kind = piece.lower()

            if kind == "p":
                self._pawn_moves(moves, square, rank, file, upper)
            elif kind == "n":
                self._step_moves(moves, square, rank, file, KNIGHT_STEPS, side)
            elif kind == "k":
                self._step_moves(moves, square, rank, file, KING_STEPS, side)
                self._castling_moves(moves, square, side)
            else:
                dirs = {"b": BISHOP_DIRS, "r": ROOK_DIRS, "q": QUEEN_DIRS}[kind]
                self._slide_moves(moves, square, rank, file, dirs, side)
        return moves

    def _pawn_moves(self, moves: list[Move], square: int, rank: int, file: int, upper: bool) -> None:
        step = -1 if upper else 1
        start_rank = 6 if upper else 1
        last_rank = 0 if upper else 7
        side = "w" if upper else "b"

        forward = rank + step
        if 0 <= forward < 8 and self.squares[forward * 8 + file] == ".":
            self._add_pawn(moves, square, forward * 8 + file, forward == last_rank)
            # двойной ход только с начальной горизонтали и только через пустое поле
            if rank == start_rank:
                jump = rank + 2 * step
                if self.squares[jump * 8 + file] == ".":
                    moves.append(Move(square, jump * 8 + file))

        for delta_file in (-1, 1):
            target_file = file + delta_file
            if not 0 <= target_file < 8 or not 0 <= forward < 8:
                continue
            target = forward * 8 + target_file
            occupant = self.squares[target]
            if occupant != "." and self.colour_of(occupant) != side:
                self._add_pawn(moves, square, target, forward == last_rank)
            elif target == self.ep:
                moves.append(Move(square, target, en_passant=True))

    @staticmethod
    def _add_pawn(moves: list[Move], frm: int, to: int, promoting: bool) -> None:
        if promoting:
            moves.extend(Move(frm, to, kind) for kind in "qrbn")
        else:
            moves.append(Move(frm, to))

    def _step_moves(self, moves, square, rank, file, steps, side) -> None:
        for delta_rank, delta_file in steps:
            r, f = rank + delta_rank, file + delta_file
            if not (0 <= r < 8 and 0 <= f < 8):
                continue
            target = r * 8 + f
            if self.colour_of(self.squares[target]) != side:
                moves.append(Move(square, target))

    def _slide_moves(self, moves, square, rank, file, dirs, side) -> None:
        for delta_rank, delta_file in dirs:
            r, f = rank + delta_rank, file + delta_file
            while 0 <= r < 8 and 0 <= f < 8:
                target = r * 8 + f
                occupant = self.squares[target]
                if occupant == ".":
                    moves.append(Move(square, target))
                else:
                    if self.colour_of(occupant) != side:
                        moves.append(Move(square, target))
                    break
                r += delta_rank
                f += delta_file

    def _castling_moves(self, moves: list[Move], square: int, side: str) -> None:
        """Рокировка: король не под шахом, поля пусты и не атакованы."""
        if self.in_check(side):
            return
        opponent = self.opponent(side)
        home = 60 if side == "w" else 4
        if square != home:
            return

        rights = ("KQ" if side == "w" else "kq")
        for right in rights:
            if right not in self.castling:
                continue
            kingside = right.lower() == "k"
            rook_frm = home + 3 if kingside else home - 4
            rook = "R" if side == "w" else "r"
            if self.squares[rook_frm] != rook:
                continue

            between = (
                range(home + 1, rook_frm) if kingside else range(rook_frm + 1, home)
            )
            if any(self.squares[sq] != "." for sq in between):
                continue

            step = 1 if kingside else -1
            path = (home, home + step, home + 2 * step)
            if any(self.is_attacked(sq, opponent) for sq in path):
                continue

            moves.append(
                Move(
                    home,
                    home + 2 * step,
                    rook_frm=rook_frm,
                    rook_to=home + step,
                )
            )

    # --- выполнение хода -----------------------------------------------------

    def make_move(self, move: Move) -> Position:
        """Возвращает новую позицию после хода; текущая не меняется."""
        after = self.copy()
        squares = after.squares
        piece = squares[move.frm]
        side = self.colour_of(piece)
        kind = piece.lower()
        captured = squares[move.to]

        squares[move.frm] = "."
        if move.promotion:
            squares[move.to] = (
                move.promotion.upper() if side == "w" else move.promotion.lower()
            )
        else:
            squares[move.to] = piece

        if move.en_passant:
            # снимаемая пешка стоит не на поле взятия, а рядом с ним
            victim = move.to + (8 if side == "w" else -8)
            captured = squares[victim]
            squares[victim] = "."

        if move.is_castling:
            squares[move.rook_to] = squares[move.rook_frm]
            squares[move.rook_frm] = "."

        # право на взятие на проходе живёт ровно один полуход
        after.ep = -1
        if kind == "p" and abs(move.to - move.frm) == 16:
            after.ep = (move.frm + move.to) // 2

        after.castling = self._castling_after(move, piece, captured)
        after.halfmove = 0 if (kind == "p" or captured != ".") else self.halfmove + 1
        after.fullmove = self.fullmove + (1 if side == "b" else 0)
        after.turn = self.opponent(side)
        return after

    def _castling_after(self, move: Move, piece: str, captured: str) -> str:
        """Пересчитывает права на рокировку после хода."""
        rights = self.castling
        if not rights:
            return ""
        kind = piece.lower()
        side = self.colour_of(piece)

        if kind == "k":
            for letter in ("K", "Q") if side == "w" else ("k", "q"):
                rights = rights.replace(letter, "")

        # уход или взятие ладьи с углового поля снимает соответствующее право
        corners = {56: "Q", 63: "K", 0: "q", 7: "k"}
        for square in (move.frm, move.to):
            right = corners.get(square)
            if right:
                rights = rights.replace(right, "")
        return rights

    # --- состояние партии ----------------------------------------------------

    def status(self) -> str:
        """Состояние: «ok», «check», «checkmate», «stalemate» или «draw»."""
        moves = self.generate_moves()
        if not moves:
            return "checkmate" if self.in_check() else "stalemate"
        if self.halfmove >= 100:
            return "draw"
        if self._insufficient_material():
            return "draw"
        return "check" if self.in_check() else "ok"

    def _insufficient_material(self) -> bool:
        """Ничья по недостатку материала: голые короли или король и лёгкая фигура."""
        rest = [piece.lower() for piece in self.squares if piece not in (".", "K", "k")]
        if not rest:
            return True
        return len(rest) == 1 and rest[0] in ("n", "b")

    def find_move(self, frm: int, to: int, promotion: str = "") -> Move | None:
        """Ищет законный ход по полям; None — такого хода нет.

        Флаги рокировки и взятия на проходе проставляет генератор, поэтому ход
        от интерфейса всегда сверяется со списком законных, а не применяется
        напрямую.
        """
        for move in self.generate_moves():
            if move.frm == frm and move.to == to:
                if move.promotion and promotion and move.promotion != promotion.lower():
                    continue
                return move
        return None

    def material(self, side: str) -> int:
        """Суммарная стоимость фигур стороны без учёта короля."""
        return sum(
            PIECE_VALUES[piece.lower()]
            for piece in self.squares
            if piece != "." and self.colour_of(piece) == side and piece.lower() != "k"
        )

    def __str__(self) -> str:
        rows = []
        for rank in range(8):
            rows.append(" ".join(self.squares[rank * 8 : rank * 8 + 8]))
        return "\n".join(rows)
