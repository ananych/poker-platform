"""Card primitives. Cards are 2-char strings: rank + suit, e.g. "Ah", "Td", "2c".

Pure module: no I/O, no framework imports (SDD §14).
"""

from __future__ import annotations

RANKS = "23456789TJQKA"
SUITS = "cdhs"
RANK_VALUE = {r: i + 2 for i, r in enumerate(RANKS)}  # '2' -> 2 ... 'A' -> 14

FULL_DECK: tuple[str, ...] = tuple(r + s for r in RANKS for s in SUITS)


def rank_of(card: str) -> int:
    return RANK_VALUE[card[0]]


def suit_of(card: str) -> str:
    return card[1]


def is_valid_card(card: str) -> bool:
    return isinstance(card, str) and len(card) == 2 and card[0] in RANK_VALUE and card[1] in SUITS
