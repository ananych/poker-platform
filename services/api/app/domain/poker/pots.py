"""Side-pot construction and integer distribution (SDD §5.3).

All amounts are non-negative integers (chip units). No floating point.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Pot:
    amount: int
    eligible_seats: tuple[int, ...]  # non-folded contenders, ascending seat order


def uncalled_refund(contributions: dict[int, int]) -> tuple[int | None, int]:
    """Return (seat, refund) for the portion of the top contribution nobody matched.

    The excess of the single largest contributor over the second-largest
    contribution (folded players included) was never called and is returned.
    """
    if len(contributions) < 2:
        return (None, 0)
    ordered = sorted(contributions.items(), key=lambda kv: kv[1], reverse=True)
    (top_seat, top), (_, second) = ordered[0], ordered[1]
    if top > second:
        return (top_seat, top - second)
    return (None, 0)


def build_pots(contributions: dict[int, int], folded: set[int]) -> list[Pot]:
    """Segment total contributions into main + side pots.

    `contributions` must already have the uncalled bet refunded.
    Folded contributions fund pots but are never eligible to win.
    """
    live = {s: c for s, c in contributions.items() if s not in folded}
    if not live:
        raise ValueError("at least one non-folded player required")
    levels = sorted({c for c in live.values() if c > 0})
    max_all = max(contributions.values(), default=0)
    if levels and max_all > levels[-1]:
        # Defensive: a folded contribution above every live level (should not
        # happen after refund). Fold it into the top pot.
        levels[-1] = max_all
    if not levels:
        return [Pot(0, tuple(sorted(live)))]

    pots: list[Pot] = []
    prev = 0
    for level in levels:
        amount = sum(min(c, level) - min(c, prev) for c in contributions.values())
        live_level = min(level, max(live.values()))
        eligible = tuple(sorted(s for s, c in live.items() if c >= live_level))
        if amount > 0:
            if pots and pots[-1].eligible_seats == eligible:
                pots[-1] = Pot(pots[-1].amount + amount, eligible)
            else:
                pots.append(Pot(amount, eligible))
        prev = level
    assert sum(p.amount for p in pots) == sum(contributions.values())
    return pots


def clockwise_from_button(
    seats: list[int] | tuple[int, ...], button: int, max_seats: int = 9
) -> list[int]:
    """Order seats clockwise starting with the first seat left of the button."""
    return sorted(seats, key=lambda s: (s - button - 1) % max_seats)


def split_pot(amount: int, winners: list[int], button: int, max_seats: int = 9) -> dict[int, int]:
    """Split integer `amount` among winners; odd chips go one at a time clockwise
    from the button (first winner left of the button gets the first odd chip)."""
    if not winners:
        raise ValueError("no winners")
    share, rem = divmod(amount, len(winners))
    out = {w: share for w in winners}
    for w in clockwise_from_button(winners, button, max_seats)[:rem]:
        out[w] += 1
    return out
