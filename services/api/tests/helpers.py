"""Test helpers: rig a started hand with exact hole cards and board."""

from __future__ import annotations

from app.domain.poker.cards import FULL_DECK
from app.domain.poker.engine import assert_invariants
from app.domain.poker.state import HandState


def rig(state: HandState, holes: dict[int, list[str]], board: list[str] | None = None) -> HandState:
    """Overwrite hole cards and arrange the deck so the board comes out as given.
    Only valid right after start_hand (before any street is dealt)."""
    board = board or []
    used: set[str] = set()
    for s, cards in holes.items():
        state.players[s].hole_cards = list(cards)
        used.update(cards)
    used.update(board)
    rest = [c for c in FULL_DECK if c not in used]
    # unspecified hole cards: assign from rest
    for p in state.players.values():
        if p.seat not in holes:
            p.hole_cards = [rest.pop(), rest.pop()]
    burns = [rest.pop() for _ in range(3)]
    seq: list[str] = []
    if board:
        seq = [burns[0], *board[:3], burns[1], board[3], burns[2], board[4]]
    else:
        rest.extend(burns)
    state.deck = rest + list(reversed(seq))
    assert_invariants(state)
    return state
