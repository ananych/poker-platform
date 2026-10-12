"""Conservation/property tests across generated legal sequences (SDD §13.1)."""

from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.poker import (
    ActionType as A,
)
from app.domain.poker import (
    HandConfig,
    Phase,
    apply_action,
    assert_invariants,
    legal_actions,
    project_hand,
    start_hand,
)
from app.domain.poker.deck import SeededRandomSource


@st.composite
def table(draw):
    n = draw(st.integers(2, 9))
    seats = sorted(draw(st.lists(st.integers(1, 9), min_size=n, max_size=n, unique=True)))
    stacks = {s: draw(st.integers(1, 400)) for s in seats}
    if sum(1 for v in stacks.values() if v > 0) < 2:
        stacks[seats[0]] = 100
    button = draw(st.sampled_from(seats))
    sb = draw(st.integers(1, 5))
    bb = draw(st.integers(sb + 1, 12))
    seed = draw(st.integers(0, 2**32))
    return stacks, button, HandConfig(sb, bb), seed


def choose(draw, la):
    opts = [A.FOLD]
    if la.can_check:
        opts.append(A.CHECK)
    if la.call_amount > 0:
        opts.append(A.CALL)
    if la.can_bet:
        opts.append(A.BET)
    if la.can_raise:
        opts.append(A.RAISE)
    if la.can_bet or la.can_raise:
        opts.append(A.ALL_IN)
    a = draw(st.sampled_from(opts))
    amt = None
    if a in (A.BET, A.RAISE):
        amt = draw(st.integers(la.min_raise_to, la.max_raise_to))
    return a, amt


@settings(max_examples=600, deadline=None)
@given(table(), st.data())
def test_random_hands_conserve_chips_and_complete(t, data):
    stacks, button, cfg, seed = t
    state, events = start_hand(cfg, stacks, button, SeededRandomSource(seed))
    total = sum(stacks.values())
    steps = 0
    while state.phase != Phase.HAND_COMPLETE:
        assert state.actor_seat is not None
        la = legal_actions(state, state.actor_seat)
        a, amt = choose(data.draw, la)
        state, ev = apply_action(state, state.actor_seat, a, amt)
        events += ev
        assert_invariants(state)
        steps += 1
        assert steps < 500
    assert sum(p.stack for p in state.players.values()) == total
    assert all(p.stack >= 0 for p in state.players.values())
    assert sum(state.result.payouts.values()) == sum(
        p.total_contribution for p in state.players.values()
    )
    # event sequence is strictly monotonic
    seqs = [e["seq"] for e in events]
    assert seqs == list(range(1, len(seqs) + 1))
    # no mucked/hidden hole card leaks in public payloads or spectator view
    hidden = {
        c for p in state.players.values() if p.show_status.value != "SHOWN" for c in p.hole_cards
    }
    public_blob = str([e["public"] for e in events]) + str(project_hand(state, None))
    for c in hidden:
        assert f"'{c}'" not in public_blob or c in state.board
