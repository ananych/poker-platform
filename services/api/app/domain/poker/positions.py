"""Hand participant / position selection (A-01, confirmed by product owner).

Policy "enter any time, moving big blind":
- Every eligible seated player (active or newly seated / returning) is dealt into
  the very next hand. Nobody has to wait for the big blind and there is no
  missed-blind debt or dead small blind.
- The big blind advances exactly one seat clockwise per hand among the
  participants; button/SB are derived backwards from the BB.
"""

from __future__ import annotations

from dataclasses import dataclass

from .errors import EngineError


@dataclass(frozen=True)
class Positions:
    participants: tuple[int, ...]
    button: int
    big_blind: int


def _cw_after(seat: int, pool: list[int], max_seats: int) -> int:
    return min(pool, key=lambda s: (s - seat - 1) % max_seats)


def _ccw_before(seat: int, pool: list[int], max_seats: int) -> int:
    return min(pool, key=lambda s: (seat - s - 1) % max_seats)


def next_hand_positions(
    active: list[int], waiting: list[int], last_bb: int | None, max_seats: int = 9
) -> Positions:
    participants = sorted(set(active) | set(waiting))
    if len(participants) < 2:
        raise EngineError("INVALID_ACTION", "at least two eligible seats required")
    if last_bb is None:
        bb = participants[min(2, len(participants) - 1)]
    else:
        bb = _cw_after(last_bb, participants, max_seats)
    if len(participants) == 2:
        button = _ccw_before(bb, participants, max_seats)
    else:
        sb = _ccw_before(bb, participants, max_seats)
        button = _ccw_before(sb, participants, max_seats)
    return Positions(tuple(participants), button, bb)
