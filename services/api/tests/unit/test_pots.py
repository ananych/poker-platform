from app.domain.poker.pots import Pot, build_pots, split_pot, uncalled_refund


def test_no_side_pot():
    assert build_pots({1: 100, 2: 100, 3: 100}, set()) == [Pot(300, (1, 2, 3))]


def test_one_side_pot():
    pots = build_pots({1: 50, 2: 200, 3: 200}, set())
    assert pots == [Pot(150, (1, 2, 3)), Pot(300, (2, 3))]


def test_two_side_pots():
    pots = build_pots({1: 50, 2: 120, 3: 300, 4: 300}, set())
    assert pots == [Pot(200, (1, 2, 3, 4)), Pot(210, (2, 3, 4)), Pot(360, (3, 4))]


def test_folded_funds_but_not_eligible():
    pots = build_pots({1: 100, 2: 40, 3: 100}, {2})
    assert pots == [Pot(240, (1, 3))]


def test_folded_and_all_in_mixed():
    # seat 3 all-in 50; seat 2 folded after putting 200; 1 and 4 to 200
    pots = build_pots({1: 200, 2: 200, 3: 50, 4: 200}, {2})
    assert pots == [Pot(200, (1, 3, 4)), Pot(450, (1, 4))]
    assert sum(p.amount for p in pots) == 650


def test_uncalled_refund():
    assert uncalled_refund({1: 500, 2: 200}) == (1, 300)
    assert uncalled_refund({1: 200, 2: 200}) == (None, 0)
    assert uncalled_refund({1: 150, 2: 50, 3: 0}) == (1, 100)


def test_odd_chip_goes_left_of_button():
    # button 5, winners 3 and 7 -> 7 is first clockwise from button
    assert split_pot(101, [3, 7], button=5) == {3: 50, 7: 51}
    # button 8: order 9,1,2..: winner 3 before 7
    assert split_pot(101, [3, 7], button=8) == {3: 51, 7: 50}


def test_three_way_odd_chips():
    out = split_pot(100, [2, 4, 6], button=4)
    assert sum(out.values()) == 100
    assert out == {6: 34, 2: 33, 4: 33}
