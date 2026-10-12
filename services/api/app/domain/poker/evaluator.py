"""Hand evaluator (SDD §5.3).

`evaluate7` returns the best five-card combination of a 7-card (or 5/6-card) hand
and a totally ordered `HandRank`. Larger HandRank wins; equal HandRanks split.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import IntEnum
from itertools import combinations

from .cards import rank_of, suit_of


class Category(IntEnum):
    HIGH_CARD = 0
    ONE_PAIR = 1
    TWO_PAIR = 2
    THREE_OF_A_KIND = 3
    STRAIGHT = 4
    FLUSH = 5
    FULL_HOUSE = 6
    FOUR_OF_A_KIND = 7
    STRAIGHT_FLUSH = 8


@dataclass(frozen=True, order=True)
class HandRank:
    category: Category
    tiebreak: tuple[int, ...]

    @property
    def name(self) -> str:
        if self.category == Category.STRAIGHT_FLUSH and self.tiebreak[0] == 14:
            return "Royal Flush"
        return self.category.name.replace("_", " ").title()


@dataclass(frozen=True)
class EvaluatedHand:
    rank: HandRank
    best_five: tuple[str, ...]


def _straight_high(ranks_desc_unique: list[int]) -> int | None:
    """Highest straight top card from unique ranks (desc); handles A-2-3-4-5 wheel."""
    rs = list(ranks_desc_unique)
    if 14 in rs:
        rs.append(1)  # ace plays low for the wheel
    run = 1
    for i in range(1, len(rs)):
        if rs[i] == rs[i - 1] - 1:
            run += 1
            if run >= 5:
                return rs[i] + 4
        else:
            run = 1
    return None


def evaluate5(cards: tuple[str, ...] | list[str]) -> HandRank:
    if len(cards) != 5:
        raise ValueError("evaluate5 requires exactly 5 cards")
    ranks = sorted((rank_of(c) for c in cards), reverse=True)
    is_flush = len({suit_of(c) for c in cards}) == 1
    unique = sorted(set(ranks), reverse=True)
    straight_high = _straight_high(unique) if len(unique) == 5 else None

    if is_flush and straight_high:
        return HandRank(Category.STRAIGHT_FLUSH, (straight_high,))

    counts = Counter(ranks)
    # sort by (count desc, rank desc)
    groups = sorted(counts.items(), key=lambda kv: (kv[1], kv[0]), reverse=True)
    shape = [cnt for _, cnt in groups]
    ordered = tuple(r for r, _ in groups)

    if shape == [4, 1]:
        return HandRank(Category.FOUR_OF_A_KIND, ordered)
    if shape == [3, 2]:
        return HandRank(Category.FULL_HOUSE, ordered)
    if is_flush:
        return HandRank(Category.FLUSH, tuple(ranks))
    if straight_high:
        return HandRank(Category.STRAIGHT, (straight_high,))
    if shape == [3, 1, 1]:
        return HandRank(Category.THREE_OF_A_KIND, ordered)
    if shape == [2, 2, 1]:
        return HandRank(Category.TWO_PAIR, ordered)
    if shape == [2, 1, 1, 1]:
        return HandRank(Category.ONE_PAIR, ordered)
    return HandRank(Category.HIGH_CARD, tuple(ranks))


def evaluate7(cards: list[str] | tuple[str, ...]) -> EvaluatedHand:
    """Best 5-of-N (N in 5..7). Deterministic best_five selection on ties."""
    if not 5 <= len(cards) <= 7:
        raise ValueError("evaluate7 requires 5 to 7 cards")
    if len(set(cards)) != len(cards):
        raise ValueError("duplicate cards")
    best: EvaluatedHand | None = None
    for combo in combinations(sorted(cards), 5):
        r = evaluate5(combo)
        if best is None or r > best.rank:
            best = EvaluatedHand(r, tuple(combo))
    assert best is not None
    return best
