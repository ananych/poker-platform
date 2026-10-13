import pytest

from app.domain.poker import (
    ActionType as A,
)
from app.domain.poker import (
    EngineError,
    HandConfig,
    Phase,
    apply_action,
    force_fold,
    legal_actions,
    next_button,
    project_hand,
    start_hand,
    timeout_action,
)
from app.domain.poker.deck import SeededRandomSource
from tests.helpers import rig

CFG = HandConfig(small_blind=5, big_blind=10)


def new(stacks, button, seed=1):
    st, ev = start_hand(CFG, stacks, button, SeededRandomSource(seed))
    return st, ev


def act(st, action, raise_to=None):
    st2, _ = apply_action(st, st.actor_seat, action, raise_to)
    return st2


# ---- positions / turn order ------------------------------------------------
def test_heads_up_button_is_sb_and_acts_first_preflop():
    st, _ = new({2: 1000, 6: 1000}, button=2)
    assert st.sb_seat == 2 and st.bb_seat == 6
    assert st.actor_seat == 2
    st = act(st, A.CALL)
    assert st.actor_seat == 6  # BB option
    st = act(st, A.CHECK)
    assert st.phase == Phase.FLOP
    assert st.actor_seat == 6  # BB acts first postflop heads-up


def test_three_handed_order():
    st, _ = new({1: 1000, 4: 1000, 7: 1000}, button=1)
    assert (st.sb_seat, st.bb_seat) == (4, 7)
    assert st.actor_seat == 1  # UTG = left of BB wraps to button
    st = act(st, A.CALL)
    st = act(st, A.CALL)  # SB completes
    assert st.actor_seat == 7
    st = act(st, A.CHECK)
    assert st.phase == Phase.FLOP and st.actor_seat == 4  # first left of button


def test_seat_vacancies_and_nine_handed():
    stacks = {s: 500 for s in range(1, 10)}
    st, _ = new(stacks, button=9)
    assert (st.sb_seat, st.bb_seat, st.actor_seat) == (1, 2, 3)
    st, _ = new({3: 500, 5: 500, 9: 500}, button=9)
    assert (st.sb_seat, st.bb_seat, st.actor_seat) == (3, 5, 9)


def test_next_button_skips_empty_seats():
    assert next_button(None, [3, 5, 8]) == 3
    assert next_button(5, [3, 5, 8]) == 8
    assert next_button(8, [3, 5, 8]) == 3


def test_requires_two_players():
    with pytest.raises(EngineError):
        start_hand(CFG, {1: 1000, 2: 0}, 1)


def test_invalid_config():
    with pytest.raises(ValueError):
        start_hand(HandConfig(10, 10), {1: 100, 2: 100}, 1)


# ---- validation --------------------------------------------------------
def test_out_of_turn_rejected():
    st, _ = new({1: 1000, 2: 1000, 3: 1000}, button=1)
    with pytest.raises(EngineError) as e:
        apply_action(st, 2, A.FOLD)
    assert e.value.code == "NOT_YOUR_TURN"


def test_check_facing_bet_rejected():
    st, _ = new({1: 1000, 2: 1000, 3: 1000}, button=1)
    with pytest.raises(EngineError) as e:
        apply_action(st, st.actor_seat, A.CHECK)
    assert e.value.code == "INVALID_ACTION"


def test_min_raise_and_insufficient_stack():
    st, _ = new({1: 1000, 2: 1000, 3: 1000}, button=1)
    la = legal_actions(st, st.actor_seat)
    assert la.min_raise_to == 20 and la.max_raise_to == 1000
    with pytest.raises(EngineError):
        apply_action(st, st.actor_seat, A.RAISE, 15)
    with pytest.raises(EngineError):
        apply_action(st, st.actor_seat, A.RAISE, 1001)
    st = act(st, A.RAISE, 35)  # raise of 25
    la = legal_actions(st, st.actor_seat)
    assert la.min_raise_to == 60  # 35 + 25


def test_input_state_not_mutated():
    st, _ = new({1: 1000, 2: 1000}, button=1)
    before = st.to_dict()
    apply_action(st, st.actor_seat, A.RAISE, 30)
    assert st.to_dict() == before


def test_min_bet_postflop_is_big_blind():
    st, _ = new({1: 1000, 2: 1000}, button=1)
    st = act(st, A.CALL)
    st = act(st, A.CHECK)
    la = legal_actions(st, st.actor_seat)
    assert la.can_bet and not la.can_raise and la.min_raise_to == 10
    with pytest.raises(EngineError):
        apply_action(st, st.actor_seat, A.BET, 9)


# ---- short all-in does not reopen ---------------------------------------
def test_short_all_in_does_not_reopen_raising():
    # seat 1 (BTN) 1000, seat 2 (SB) 1000, seat 3 (BB) 1000, seat 4 has 130
    st, _ = new({1: 1000, 2: 1000, 3: 1000, 4: 130}, button=1)
    assert st.actor_seat == 4
    st = act(st, A.CALL)  # 4 calls 10
    st = act(st, A.RAISE, 100)  # 1 raises to 100 (inc 90)
    st = act(st, A.FOLD)  # 2 folds
    st = act(st, A.CALL)  # 3 calls 100
    assert st.actor_seat == 4
    st = act(st, A.ALL_IN)  # 4 all-in to 130: short raise (+30 < 90)
    assert st.current_bet == 130 and st.min_raise_increment == 90
    assert st.actor_seat == 1
    la = legal_actions(st, 1)
    assert not la.can_raise and la.call_amount == 30
    with pytest.raises(EngineError):
        apply_action(st, 1, A.RAISE, 300)
    st = act(st, A.CALL)
    la3 = legal_actions(st, 3)
    assert not la3.can_raise
    st = act(st, A.CALL)
    assert st.phase == Phase.FLOP


def test_player_who_has_not_acted_may_raise_after_short_all_in():
    st, _ = new({1: 1000, 2: 1000, 3: 1000, 4: 1000, 5: 55}, button=1)
    assert st.actor_seat == 4
    st = act(st, A.RAISE, 40)  # 4 raises to 40 (inc 30)
    st = act(st, A.ALL_IN)  # 5 all-in 55 (short +15)
    assert st.current_bet == 55 and st.min_raise_increment == 30
    assert legal_actions(st, 1).can_raise  # BTN has not acted yet
    assert legal_actions(st, 1).min_raise_to == 85
    st = act(st, A.CALL)  # 1
    st = act(st, A.FOLD)  # 2
    st = act(st, A.CALL)  # 3 (BB has not voluntarily acted)
    assert st.actor_seat == 4
    assert not legal_actions(st, 4).can_raise  # faced only +15 since acting


def test_cumulative_short_raises_reopen():
    stacks = {1: 1000, 2: 1000, 3: 1000, 4: 25, 5: 31}
    st, _ = new(stacks, button=1)
    # limp around preflop: 4, 5, 1 call 10, SB completes, BB checks
    for a in (A.CALL, A.CALL, A.CALL, A.CALL, A.CHECK):
        st = act(st, a)
    assert st.phase == Phase.FLOP and st.actor_seat == 2
    st = act(st, A.BET, 10)  # 2 bets 10 (min inc 10)
    st = act(st, A.CALL)  # 3 calls 10
    st = act(st, A.ALL_IN)  # 4 all-in 15 (+5 short)
    st = act(st, A.ALL_IN)  # 5 all-in 21 (+6 short; cumulative +11 over 10)
    assert st.min_raise_increment == 10
    st = act(st, A.CALL)  # 1 calls 21 (had not acted: could raise)
    assert st.actor_seat == 2
    la = legal_actions(st, 2)
    assert la.can_raise and la.min_raise_to == 31  # 21 - 10 >= 10 -> reopened


# ---- streets & payouts ---------------------------------------------------
def test_uncontested_win_refunds_uncalled_bet():
    st, _ = new({1: 1000, 2: 1000, 3: 1000}, button=1)
    st = act(st, A.RAISE, 100)  # BTN
    st = act(st, A.FOLD)  # SB
    st = act(st, A.FOLD)  # BB
    assert st.phase == Phase.HAND_COMPLETE
    assert st.result.refunds == {1: 90}
    assert st.players[1].stack == 1015
    assert st.players[2].stack == 995 and st.players[3].stack == 990
    assert not st.result.hands  # nothing shown


def test_bb_walk():
    st, _ = new({1: 1000, 2: 1000, 3: 1000}, button=1)
    st = act(st, A.FOLD)
    st = act(st, A.FOLD)
    assert st.phase == Phase.HAND_COMPLETE
    assert st.players[3].stack == 1005


def test_full_showdown_shows_all_live_hands():
    st, _ = new({1: 1000, 2: 1000}, button=1)
    rig(st, {1: ["Ah", "Ad"], 2: ["7c", "2d"]}, ["Ks", "9h", "4c", "3s", "Jd"])
    st = act(st, A.CALL)
    st = act(st, A.CHECK)
    for _ in range(3):
        st = act(st, A.CHECK)
        st = act(st, A.CHECK)
    assert st.phase == Phase.HAND_COMPLETE
    assert st.players[1].stack == 1010 and st.players[2].stack == 990
    assert set(st.result.hands) == {1, 2}  # A-02: everyone at showdown shows
    view = project_hand(st, viewer_seat=None)
    seat2 = next(s for s in view["seats"] if s["seat_no"] == 2)
    assert seat2["shown_cards"] == ["7c", "2d"]


def test_folded_hands_stay_hidden_at_showdown():
    st, _ = new({1: 1000, 2: 1000, 3: 1000}, button=1)
    rig(st, {1: ["Ah", "Ad"], 2: ["7c", "2d"], 3: ["Kc", "Qc"]}, ["Ks", "9h", "4c", "3s", "Jd"])
    st = act(st, A.CALL)  # 1
    st = act(st, A.FOLD)  # 2 (SB) folds
    st = act(st, A.CHECK)  # 3
    for _ in range(3):
        st = act(st, A.CHECK)
        st = act(st, A.CHECK)
    assert set(st.result.hands) == {1, 3}
    view = project_hand(st, viewer_seat=None)
    assert "shown_cards" not in next(s for s in view["seats"] if s["seat_no"] == 2)


def test_split_pot_with_odd_chip():
    st, _ = new({1: 1000, 2: 1000, 3: 1000}, button=1)
    rig(st, {1: ["2c", "3d"], 2: ["2h", "3s"], 3: ["4c", "5d"]}, ["Ah", "Kh", "Qd", "Js", "9c"])
    st = act(st, A.CALL)  # 1
    st = act(st, A.CALL)  # 2 (SB)
    st = act(st, A.CHECK)  # 3 -> flop
    st = act(st, A.BET, 15)  # 2
    st = act(st, A.FOLD)  # 3 folds after putting 10 preflop
    st = act(st, A.CALL)  # 1
    for _ in range(2):
        st = act(st, A.CHECK)
        st = act(st, A.CHECK)
    # pot = 30 + 30 = 60 -> 1 and 2 split 30 each? board is AKQJ9; both have
    # A-high board play, tie.
    assert st.result.pots[0]["winners"] == [1, 2]
    assert st.players[1].stack + st.players[2].stack + st.players[3].stack == 3000


def test_odd_chip_settlement_left_of_button():
    st, _ = new({1: 1000, 2: 1000, 3: 1000}, button=1)
    rig(st, {1: ["2c", "3d"], 2: ["2h", "3s"], 3: ["4c", "6d"]}, ["Ah", "Kh", "Qd", "Js", "9c"])
    st = act(st, A.CALL)  # 1: 10
    st = act(st, A.CALL)  # 2: 10
    st = act(st, A.RAISE, 25)  # 3 raises to 25
    st = act(st, A.CALL)  # 1: 25
    st = act(st, A.FOLD)  # 2 folds (10 in)
    # flop: 3 and 1 remain (board plays for both: tie). pot = 25+25+10 = 60
    for _ in range(3):
        st = act(st, A.CHECK)
        st = act(st, A.CHECK)
    assert st.players[1].stack == 1005 and st.players[3].stack == 1005
    assert st.players[2].stack == 990


def test_side_pots_all_in_runout_shows_all():
    st, _ = new({1: 100, 2: 300, 3: 1000}, button=1)
    rig(st, {1: ["Ah", "Ad"], 2: ["Kh", "Kd"], 3: ["Qh", "Qd"]}, ["2c", "7s", "9d", "3c", "4s"])
    st = act(st, A.ALL_IN)  # 1 all-in 100
    st = act(st, A.ALL_IN)  # 2 (SB) all-in 300
    st = act(st, A.CALL)  # 3 calls 300
    assert st.phase == Phase.HAND_COMPLETE
    assert len(st.board) == 5
    assert st.players[1].stack == 300  # main pot 3*100
    assert st.players[2].stack == 400  # side pot 2*200
    assert st.players[3].stack == 700
    assert set(st.result.hands) == {1, 2, 3}  # runout: all shown


def test_blind_all_in_short():
    st, _ = new({1: 1000, 2: 3, 3: 7}, button=1)
    assert st.players[2].all_in and st.players[3].all_in
    assert st.actor_seat == 1
    st = act(st, A.CALL)
    assert st.phase == Phase.HAND_COMPLETE
    total = sum(p.stack for p in st.players.values())
    assert total == 1010
    # BTN called 10, only 7 matched -> 3 refunded
    assert st.result.refunds.get(1) == 3


def test_timeout_always_folds_by_default():
    st, _ = new({1: 1000, 2: 1000}, button=1)
    st2, ev = timeout_action(st)  # SB facing BB -> fold
    assert ev[0]["public"]["action"] == "FOLD" and ev[0]["public"]["timeout"]
    st = act(st, A.CALL)
    _, ev = timeout_action(st)  # BB option: still folds (product rule)
    assert ev[0]["public"]["action"] == "FOLD"


def test_timeout_check_or_fold_policy():
    st, _ = new({1: 1000, 2: 1000}, button=1)
    _, ev = timeout_action(st, check_if_possible=True)
    assert ev[0]["public"]["action"] == "FOLD"
    st = act(st, A.CALL)
    st3, ev = timeout_action(st, check_if_possible=True)  # BB option -> check
    assert ev[0]["public"]["action"] == "CHECK"
    assert st3.phase == Phase.FLOP


def test_force_fold_out_of_turn_and_all_in_noop():
    st, _ = new({1: 1000, 2: 1000, 3: 1000}, button=1)
    st, ev = force_fold(st, 3)
    assert st.players[3].folded and ev
    st = act(st, A.FOLD)  # 1 folds -> SB wins
    assert st.phase == Phase.HAND_COMPLETE


def test_private_cards_only_in_private_events():
    st, ev = new({1: 1000, 2: 1000, 3: 1000}, button=1)
    for e in ev:
        assert "hole_cards" not in e["public"]
    priv = [e for e in ev if e["type"] == "hand.your_cards"]
    assert {e["private_to"] for e in priv} == {1, 2, 3}
    v = project_hand(st, viewer_seat=2)
    assert v["your_cards"] == st.players[2].hole_cards
    flat = str(project_hand(st, viewer_seat=None))
    for p in st.players.values():
        for c in p.hole_cards:
            assert f"'{c}'" not in flat
    assert "deck" not in v


def test_state_json_roundtrip_mid_and_end():
    import json

    from app.domain.poker.state import HandState

    st, _ = new({1: 1000, 2: 1000, 3: 1000}, button=1)
    st = act(st, A.RAISE, 30)
    back = HandState.from_dict(json.loads(json.dumps(st.to_dict())))
    assert back.to_dict() == st.to_dict()
    st = act(back, A.FOLD)
    st = act(st, A.FOLD)
    back = HandState.from_dict(json.loads(json.dumps(st.to_dict())))
    assert back.to_dict() == st.to_dict() and back.result.payouts == st.result.payouts
