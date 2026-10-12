from app.domain.poker import HandConfig, start_hand
from app.domain.poker.positions import next_hand_positions


def test_table_start_everyone_enters():
    p = next_hand_positions([], [1, 4, 7], None)
    assert p.participants == (1, 4, 7) and p.big_blind == 7 and p.button == 1


def test_heads_up_start():
    p = next_hand_positions([], [3, 8], None)
    assert p.participants == (3, 8) and p.big_blind == 8 and p.button == 3


def test_bb_advances_one_seat():
    p = next_hand_positions([1, 4, 7], [], 7)
    assert p.big_blind == 1 and p.button == 4  # SB 7, BB 1


def test_new_player_enters_next_hand_immediately():
    # A-01: no waiting for the big blind
    p = next_hand_positions([1, 2], [5], 2)
    assert 5 in p.participants and p.big_blind == 5
    p = next_hand_positions([1, 2, 5], [3], 5)
    assert 3 in p.participants and p.big_blind == 1  # 3 enters without posting


def test_engine_agrees_on_bb():
    for active, waiting, last in [
        ([1, 4, 7], [], 7),
        ([1, 2], [5], 2),
        ([], [3, 8], None),
        ([2, 9], [], 9),
        ([1, 2, 3, 4], [6], 4),
    ]:
        pos = next_hand_positions(active, waiting, last)
        st, _ = start_hand(HandConfig(1, 2), {s: 100 for s in pos.participants}, pos.button)
        assert st.bb_seat == pos.big_blind
