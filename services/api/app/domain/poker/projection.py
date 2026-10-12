"""Authorized per-recipient projections (SDD §1.2, §8, §10).

Never include: deck remainder, burned cards, unrevealed/mucked hole cards of
other players. A viewer sees their own hole cards only via `viewer_seat`.
Spectators pass viewer_seat=None.
"""

from __future__ import annotations

from typing import Any

from .engine import legal_actions
from .state import HandState, ShowStatus


def project_hand(state: HandState, viewer_seat: int | None) -> dict[str, Any]:
    seats = []
    for s in state.seats_in_order():
        p = state.players[s]
        entry: dict[str, Any] = {
            "seat_no": s,
            "stack": p.stack,
            "street_contribution": p.street_contribution,
            "total_contribution": p.total_contribution,
            "folded": p.folded,
            "all_in": p.all_in,
            "has_cards": bool(p.hole_cards) and not p.folded,
        }
        if p.show_status == ShowStatus.SHOWN:
            entry["shown_cards"] = list(p.hole_cards)
        seats.append(entry)

    view: dict[str, Any] = {
        "phase": state.phase.value,
        "button_seat": state.button_seat,
        "sb_seat": state.sb_seat,
        "bb_seat": state.bb_seat,
        "actor_seat": state.actor_seat,
        "current_bet": state.current_bet,
        "min_full_raise_increment": state.min_raise_increment,
        "pot": state.pot_total(),
        "community_cards": list(state.board),
        "seats": seats,
    }
    if viewer_seat is not None and viewer_seat in state.players:
        view["your_seat"] = viewer_seat
        view["your_cards"] = list(state.players[viewer_seat].hole_cards)
        if state.actor_seat == viewer_seat:
            view["legal_actions"] = legal_actions(state, viewer_seat).to_dict()
    return view
