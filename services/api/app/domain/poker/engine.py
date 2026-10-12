"""Pure No-Limit Hold'em engine (SDD §5).

Callable without HTTP/WebSocket/DB. Every public mutator takes a HandState and
returns a NEW HandState plus a list of events; the input is never mutated.

Event shape (persisted to hand_events by the service layer):
    {"seq": int, "type": str, "public": {...}, "private_to": seat | None, "private": {...} | None}
Public payloads are safe for every room member/spectator. Private payloads go
only to the owning seat and must be encrypted at rest.
"""

from __future__ import annotations

import copy
from typing import Any

from .deck import RandomSource, shuffled_deck
from .errors import EngineError, InvariantViolation
from .evaluator import evaluate7
from .pots import build_pots, clockwise_from_button, split_pot, uncalled_refund
from .state import (
    BETTING_PHASES,
    ActionType,
    HandConfig,
    HandResult,
    HandState,
    LegalActions,
    Phase,
    PlayerState,
    ShowStatus,
)

Event = dict[str, Any]


# --------------------------------------------------------------------------
# seat helpers
# --------------------------------------------------------------------------
def _next_clockwise(from_seat: int, candidates: list[int], max_seats: int) -> int | None:
    """First candidate strictly left of (clockwise after) `from_seat`."""
    if not candidates:
        return None
    return min(candidates, key=lambda s: (s - from_seat - 1) % max_seats)


def next_button(prev_button: int | None, eligible_seats: list[int], max_seats: int = 9) -> int:
    """Simple moving button for v1 (dead-button rules deferred, see A-01)."""
    if not eligible_seats:
        raise EngineError("INVALID_ACTION", "no eligible seats")
    if prev_button is None:
        return min(eligible_seats)
    nxt = _next_clockwise(prev_button, eligible_seats, max_seats)
    assert nxt is not None
    return nxt


def _emit(
    state: HandState,
    events: list[Event],
    etype: str,
    public: dict[str, Any],
    private_to: int | None = None,
    private: dict[str, Any] | None = None,
) -> None:
    state.seq += 1
    events.append(
        {
            "seq": state.seq,
            "type": etype,
            "public": public,
            "private_to": private_to,
            "private": private,
        }
    )


# --------------------------------------------------------------------------
# hand setup
# --------------------------------------------------------------------------
def start_hand(
    config: HandConfig, stacks: dict[int, int], button_seat: int, rng: RandomSource | None = None
) -> tuple[HandState, list[Event]]:
    """HAND_SETUP: positions, shuffle, deal, forced bets → PREFLOP."""
    config.validate()
    seats = sorted(s for s, st in stacks.items() if st > 0)
    for s, st in stacks.items():
        if not isinstance(st, int) or st < 0:
            raise EngineError("INVALID_BUYIN", f"seat {s} has invalid stack")
        if not 1 <= s <= config.max_seats:
            raise EngineError("INVALID_ACTION", f"seat {s} out of range")
    if len(seats) < 2:
        raise EngineError("INVALID_ACTION", "at least two eligible seats with chips required")
    if button_seat not in seats:
        raise EngineError("INVALID_ACTION", "button must be an eligible seat")

    ms = config.max_seats
    if len(seats) == 2:
        sb = button_seat  # heads-up: button posts SB and acts first preflop
        bb = _next_clockwise(button_seat, seats, ms)
    else:
        sb = _next_clockwise(button_seat, seats, ms)
        bb = _next_clockwise(sb, seats, ms)  # type: ignore[arg-type]
    assert sb is not None and bb is not None

    players = {s: PlayerState(seat=s, stack=stacks[s]) for s in seats}
    state = HandState(
        config=config,
        button_seat=button_seat,
        sb_seat=sb,
        bb_seat=bb,
        players=players,
        deck=shuffled_deck(rng),
        starting_total=sum(stacks[s] for s in seats),
    )
    events: list[Event] = []
    _emit(
        state,
        events,
        "hand.started",
        {
            "button_seat": button_seat,
            "sb_seat": sb,
            "bb_seat": bb,
            "seats": [{"seat_no": s, "stack": stacks[s]} for s in seats],
            "small_blind": config.small_blind,
            "big_blind": config.big_blind,
            "rules_version": config.rules_version,
        },
    )

    # deal two rounds, one card at a time, starting left of the button
    order = clockwise_from_button(seats, button_seat, ms)
    for _ in range(2):
        for s in order:
            players[s].hole_cards.append(state.deck.pop())
    for s in order:
        _emit(
            state,
            events,
            "hand.your_cards",
            {"seat_no": s},
            private_to=s,
            private={"hole_cards": list(players[s].hole_cards)},
        )

    # forced bets, limited by stack (may produce all-in)
    for seat, amount, kind in ((sb, config.small_blind, "SB"), (bb, config.big_blind, "BB")):
        posted = _commit(players[seat], amount)
        _emit(
            state,
            events,
            "blind.posted",
            {"seat_no": seat, "blind": kind, "amount": posted, "all_in": players[seat].all_in},
        )

    state.current_bet = config.big_blind
    state.min_raise_increment = config.big_blind
    state.phase = Phase.PREFLOP
    _emit(state, events, "hand.street_changed", {"phase": Phase.PREFLOP.value, "board": []})

    _advance(state, events, after_seat=bb)
    assert_invariants(state)
    return state, events


def _commit(p: PlayerState, amount: int) -> int:
    put = min(amount, p.stack)
    p.stack -= put
    p.street_contribution += put
    p.total_contribution += put
    if p.stack == 0:
        p.all_in = True
    return put


# --------------------------------------------------------------------------
# legal action computation (server-side only; SDD §5.2)
# --------------------------------------------------------------------------
def _needs_action(state: HandState, p: PlayerState) -> bool:
    return p.can_act and (not p.acted_this_street or p.street_contribution < state.current_bet)


def _next_needing_action(state: HandState, after_seat: int) -> int | None:
    cands = [s for s in state.seats_in_order() if _needs_action(state, state.players[s])]
    return _next_clockwise(after_seat, cands, state.config.max_seats)


def legal_actions(state: HandState, seat: int) -> LegalActions:
    if state.phase not in BETTING_PHASES or state.actor_seat != seat:
        return LegalActions(seat, False, False, 0, False, False, 0, 0)
    p = state.players[seat]
    to_call = max(0, state.current_bet - p.street_contribution)
    max_to = p.street_contribution + p.stack
    others_can_act = any(o.can_act for s, o in state.players.items() if s != seat)
    has_rights = (not p.acted_this_street) or (
        state.current_bet - p.bet_faced_when_acted >= state.min_raise_increment
    )
    can_bet = state.current_bet == 0 and p.stack > 0 and has_rights and others_can_act
    can_raise = (
        state.current_bet > 0 and max_to > state.current_bet and has_rights and others_can_act
    )
    if state.current_bet == 0:
        min_to = min(state.config.big_blind, max_to)
    else:
        min_to = min(state.current_bet + state.min_raise_increment, max_to)
    return LegalActions(
        seat=seat,
        can_fold=True,
        can_check=to_call == 0,
        call_amount=min(to_call, p.stack) if to_call > 0 else 0,
        can_bet=can_bet,
        can_raise=can_raise,
        min_raise_to=min_to if (can_bet or can_raise) else 0,
        max_raise_to=max_to if (can_bet or can_raise) else 0,
    )


# --------------------------------------------------------------------------
# reducer
# --------------------------------------------------------------------------
def apply_action(
    state: HandState, seat: int, action: ActionType | str, raise_to: int | None = None
) -> tuple[HandState, list[Event]]:
    """Validate and apply one player action. `raise_to` is the desired TOTAL
    street contribution (Appendix B), not an increment."""
    action = ActionType(action)
    if state.phase not in BETTING_PHASES:
        raise EngineError("INVALID_ACTION", f"no betting in phase {state.phase.value}")
    if state.actor_seat != seat:
        raise EngineError("NOT_YOUR_TURN", "Only the current actor may submit a poker action.")

    st = copy.deepcopy(state)
    p = st.players[seat]
    la = legal_actions(st, seat)
    to_call = max(0, st.current_bet - p.street_contribution)
    events: list[Event] = []

    if action == ActionType.ALL_IN:
        total = p.street_contribution + p.stack
        if p.stack == 0:
            raise EngineError("INVALID_ACTION", "no chips behind")
        if total <= st.current_bet:
            action = ActionType.CALL
        elif la.can_bet:
            action, raise_to = ActionType.BET, total
        elif la.can_raise:
            action, raise_to = ActionType.RAISE, total
        else:
            raise EngineError("INVALID_ACTION", "raising is not re-opened for this player")

    public: dict[str, Any] = {"seat_no": seat, "action": action.value}
    if action == ActionType.FOLD:
        p.folded = True
    elif action == ActionType.CHECK:
        if not la.can_check:
            raise EngineError("INVALID_ACTION", "cannot check facing a bet")
    elif action == ActionType.CALL:
        if to_call == 0:
            raise EngineError("INVALID_ACTION", "nothing to call")
        public["amount"] = _commit(p, to_call)
    elif action in (ActionType.BET, ActionType.RAISE):
        allowed = la.can_bet if action == ActionType.BET else la.can_raise
        if not allowed:
            raise EngineError("INVALID_ACTION", f"{action.value} not allowed")
        if not isinstance(raise_to, int) or isinstance(raise_to, bool):
            raise EngineError("INVALID_ACTION", "raise_to must be an integer")
        if raise_to > la.max_raise_to:
            raise EngineError("INVALID_ACTION", "insufficient stack")
        if raise_to < la.min_raise_to and raise_to != la.max_raise_to:
            raise EngineError("INVALID_ACTION", f"minimum is {la.min_raise_to}")
        if raise_to <= st.current_bet:
            raise EngineError("INVALID_ACTION", "must exceed current bet")
        increment = raise_to - st.current_bet
        full = increment >= st.min_raise_increment
        _commit(p, raise_to - p.street_contribution)
        if full:
            st.min_raise_increment = increment
        st.current_bet = raise_to
        st.last_aggressor_seat = seat
        public.update({"raise_to": raise_to, "full_raise": full})
    public["all_in"] = p.all_in
    p.acted_this_street = True
    p.bet_faced_when_acted = st.current_bet
    _emit(st, events, "action.result", public)
    _advance(st, events, after_seat=seat)
    assert_invariants(st)
    return st, events


def timeout_action(state: HandState) -> tuple[HandState, list[Event]]:
    """Server-clock timeout: Check if legal, else Fold (SDD §2, §5.2)."""
    if state.actor_seat is None:
        raise EngineError("INVALID_ACTION", "no actor")
    seat = state.actor_seat
    la = legal_actions(state, seat)
    st, events = apply_action(state, seat, ActionType.CHECK if la.can_check else ActionType.FOLD)
    events[0]["public"]["timeout"] = True
    return st, events


def force_fold(state: HandState, seat: int) -> tuple[HandState, list[Event]]:
    """Leave/kick mid-hand: fold only if the player is still entitled to act
    and not all-in (SDD §3, §4). Otherwise a no-op (settle normally)."""
    p = state.players.get(seat)
    if state.phase not in BETTING_PHASES or p is None or not p.can_act:
        return state, []
    if state.actor_seat == seat:
        return apply_action(state, seat, ActionType.FOLD)
    st = copy.deepcopy(state)
    st.players[seat].folded = True
    events: list[Event] = []
    _emit(st, events, "action.result", {"seat_no": seat, "action": "FOLD", "forced": True})
    if len(st.live_seats()) == 1:
        _advance(st, events, after_seat=seat)
    assert_invariants(st)
    return st, events


# --------------------------------------------------------------------------
# progression
# --------------------------------------------------------------------------
def _round_complete(st: HandState) -> bool:
    actionable = [st.players[s] for s in st.actionable_seats()]
    if not actionable:
        return True
    if len(actionable) == 1 and actionable[0].street_contribution >= st.current_bet:
        return True  # nobody left to bet against
    return not any(_needs_action(st, p) for p in actionable)


def _advance(st: HandState, events: list[Event], after_seat: int) -> None:
    while True:
        if len(st.live_seats()) == 1:
            _settle(st, events, showdown=False)
            return
        if not _round_complete(st):
            st.actor_seat = _next_needing_action(st, after_seat)
            return
        if st.phase == Phase.RIVER:
            _settle(st, events, showdown=True)
            return
        _deal_next_street(st, events)
        after_seat = st.button_seat  # postflop: first eligible left of button


def _deal_next_street(st: HandState, events: list[Event]) -> None:
    nxt = {Phase.PREFLOP: Phase.FLOP, Phase.FLOP: Phase.TURN, Phase.TURN: Phase.RIVER}[st.phase]
    st.burned.append(st.deck.pop())
    n = 3 if nxt == Phase.FLOP else 1
    new_cards = [st.deck.pop() for _ in range(n)]
    st.board.extend(new_cards)
    st.phase = nxt
    for p in st.players.values():
        p.street_contribution = 0
        p.acted_this_street = False
        p.bet_faced_when_acted = 0
    st.current_bet = 0
    st.min_raise_increment = st.config.big_blind
    st.last_aggressor_seat = None
    st.actor_seat = None
    _emit(
        st,
        events,
        "hand.street_changed",
        {"phase": nxt.value, "board": list(st.board), "new_cards": new_cards},
    )


def _settle(st: HandState, events: list[Event], showdown: bool) -> None:
    st.actor_seat = None
    contributions = {s: p.total_contribution for s, p in st.players.items()}
    folded = {s for s, p in st.players.items() if p.folded}
    refunds: dict[int, int] = {}
    r_seat, r_amt = uncalled_refund(contributions)
    if r_seat is not None and r_amt > 0:
        contributions[r_seat] -= r_amt
        refunds[r_seat] = r_amt
        _emit(st, events, "chips.uncalled_refund", {"seat_no": r_seat, "amount": r_amt})

    pots = build_pots(contributions, folded)
    payouts: dict[int, int] = dict(refunds)
    shown: dict[int, dict[str, Any]] = {}
    ms = st.config.max_seats

    if showdown:
        st.phase = Phase.SHOWDOWN
        live = st.live_seats()
        evals = {s: evaluate7(st.players[s].hole_cards + st.board) for s in live}
        pot_dicts: list[dict[str, Any]] = []
        for i, pot in enumerate(pots):
            best = max(evals[s].rank for s in pot.eligible_seats)
            winners = [s for s in pot.eligible_seats if evals[s].rank == best]
            for s, amt in split_pot(pot.amount, winners, st.button_seat, ms).items():
                payouts[s] = payouts.get(s, 0) + amt
            pot_dicts.append(
                {
                    "index": i,
                    "amount": pot.amount,
                    "eligible": list(pot.eligible_seats),
                    "winners": winners,
                }
            )
        # Disclosure policy (A-02, confirmed by product owner): every hand that
        # reaches showdown is shown; nobody may muck. Folded hands stay secret.
        start = st.last_aggressor_seat if st.last_aggressor_seat in live else None
        order = clockwise_from_button(live, st.button_seat, ms)
        if start is not None:
            order = [start] + [s for s in order if s != start]
        for s in order:
            p = st.players[s]
            p.show_status = ShowStatus.SHOWN
            ev = evals[s]
            shown[s] = {
                "hole_cards": list(p.hole_cards),
                "rank": ev.rank.name,
                "best_five": list(ev.best_five),
            }
        _emit(
            st,
            events,
            "hand.showdown",
            {
                "board": list(st.board),
                "shown": [{"seat_no": s, **shown[s]} for s in order if s in shown],
                "mucked": [s for s in order if s not in shown],
            },
        )
    else:
        winner = st.live_seats()[0]
        for pot in pots:
            payouts[winner] = payouts.get(winner, 0) + pot.amount
        pot_dicts = [
            {"index": i, "amount": pot.amount, "eligible": [winner], "winners": [winner]}
            for i, pot in enumerate(pots)
        ]

    st.phase = Phase.SETTLEMENT
    for s, amt in payouts.items():
        st.players[s].stack += amt
    st.result = HandResult(payouts=payouts, refunds=refunds, pots=pot_dicts, hands=shown)
    st.phase = Phase.HAND_COMPLETE
    _emit(
        st,
        events,
        "hand.completed",
        {
            "pots": pot_dicts,
            "payouts": {str(k): v for k, v in payouts.items()},
            "stacks": {str(s): p.stack for s, p in st.players.items()},
            "board": list(st.board),
            "uncontested": not showdown,
        },
    )


# --------------------------------------------------------------------------
# invariants (SDD §1.2, §13.1)
# --------------------------------------------------------------------------
def assert_invariants(st: HandState) -> None:
    for p in st.players.values():
        if p.stack < 0 or p.street_contribution < 0 or p.total_contribution < 0:
            raise InvariantViolation(f"negative chips at seat {p.seat}")
        if p.street_contribution > p.total_contribution:
            raise InvariantViolation("street contribution exceeds total")
    if st.phase == Phase.HAND_COMPLETE:
        total = sum(p.stack for p in st.players.values())
    else:
        total = sum(p.stack + p.total_contribution for p in st.players.values())
    if total != st.starting_total:
        raise InvariantViolation(f"chip conservation broken: {total} != {st.starting_total}")
    cards = list(st.deck) + list(st.board) + list(st.burned)
    for p in st.players.values():
        cards.extend(p.hole_cards)
    if len(cards) != 52 or len(set(cards)) != 52:
        raise InvariantViolation("card set corrupted (duplicates or missing cards)")
