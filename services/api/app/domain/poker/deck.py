"""Deck shuffling (SDD §5.2).

Real games MUST use the OS CSPRNG (`secrets.SystemRandom`). A seeded RNG may be
injected only by tests. The deck is shuffled exactly once per hand.
"""

from __future__ import annotations

import secrets
from typing import Protocol

from .cards import FULL_DECK


class RandomSource(Protocol):
    def randbelow(self, n: int) -> int: ...


class SystemRandomSource:
    """OS CSPRNG source — the only source allowed in production."""

    def randbelow(self, n: int) -> int:
        return secrets.randbelow(n)


class SeededRandomSource:
    """Deterministic source for tests ONLY. Never use for real games."""

    def __init__(self, seed: int) -> None:
        import random

        self._rng = random.Random(seed)

    def randbelow(self, n: int) -> int:
        return self._rng.randrange(n)


def shuffled_deck(rng: RandomSource | None = None) -> list[str]:
    """Fisher–Yates shuffle of a fresh 52-card deck."""
    rng = rng or SystemRandomSource()
    deck = list(FULL_DECK)
    for i in range(len(deck) - 1, 0, -1):
        j = rng.randbelow(i + 1)
        deck[i], deck[j] = deck[j], deck[i]
    return deck
