import pytest

from app.domain.poker.evaluator import Category, evaluate5, evaluate7


def cat(cards: str) -> Category:
    return evaluate7(cards.split()).rank.category


@pytest.mark.parametrize(
    "cards,expected",
    [
        ("Ah Kh Qh Jh Th 2c 3d", Category.STRAIGHT_FLUSH),
        ("5d 4d 3d 2d Ad Kc Qs", Category.STRAIGHT_FLUSH),  # steel wheel
        ("9c 9d 9h 9s 2c 3d 4h", Category.FOUR_OF_A_KIND),
        ("Kc Kd Kh 2s 2c 3d 4h", Category.FULL_HOUSE),
        ("2h 7h 9h Jh Kh Ac Ad", Category.FLUSH),
        ("Ac 2d 3h 4s 5c Kd Qh", Category.STRAIGHT),  # wheel
        ("Tc Jd Qh Ks Ac 2d 3h", Category.STRAIGHT),  # broadway
        ("7c 7d 7h Ks 2c 3d 9h", Category.THREE_OF_A_KIND),
        ("7c 7d 9h 9s 2c 3d Kh", Category.TWO_PAIR),
        ("7c 7d 9h Js 2c 3d Kh", Category.ONE_PAIR),
        ("7c 4d 9h Js 2c 3d Kh", Category.HIGH_CARD),
    ],
)
def test_categories(cards, expected):
    assert cat(cards) == expected


def test_wheel_is_lowest_straight():
    wheel = evaluate5("Ac 2d 3h 4s 5c".split())
    six_high = evaluate5("2d 3h 4s 5c 6d".split())
    assert six_high > wheel
    assert wheel.tiebreak == (5,)


def test_no_wraparound_straight():
    assert evaluate5("Qc Kd Ah 2s 3c".split()).category == Category.HIGH_CARD


def test_seven_card_straight_picks_highest():
    ev = evaluate7("4c 5d 6h 7s 8c 9d 2h".split())
    assert ev.rank.category == Category.STRAIGHT and ev.rank.tiebreak == (9,)
    assert sorted(ev.best_five) == sorted("5d 6h 7s 8c 9d".split())


def test_flush_uses_top_five_of_suit():
    ev = evaluate7("2h 4h 6h 8h Th Qh Ac".split())
    assert ev.rank.category == Category.FLUSH
    assert ev.rank.tiebreak == (12, 10, 8, 6, 4)


def test_kickers_decide():
    a = evaluate7("Ac Ad Kh 9s 7c 4d 2h".split()).rank
    b = evaluate7("Ac Ad Qh 9s 7c 4d 2h".split()).rank
    assert a > b


def test_two_pair_fifth_card_kicker():
    a = evaluate7("Kc Kd 5h 5s Ac 2d 3h".split()).rank
    b = evaluate7("Kc Kd 5h 5s Qc 2d 3h".split()).rank
    assert a > b


def test_full_house_ordering_trips_first():
    a = evaluate7("3c 3d 3h 2s 2c 9d Th".split()).rank  # 333 22
    b = evaluate7("2c 2d 2h As Ac 9d Th".split()).rank  # 222 AA
    assert a > b


def test_two_trips_make_best_full_house():
    ev = evaluate7("9c 9d 9h 5s 5c 5d Ah".split())
    assert ev.rank.category == Category.FULL_HOUSE
    assert ev.rank.tiebreak == (9, 5)


def test_board_plays_tie():
    board = "Ac Kd Qh Js Tc".split()
    a = evaluate7(board + ["2c", "3d"]).rank
    b = evaluate7(board + ["4h", "5s"]).rank
    assert a == b


def test_quads_kicker():
    a = evaluate7("9c 9d 9h 9s Ac 2d 3h".split()).rank
    b = evaluate7("9c 9d 9h 9s Kc 2d 3h".split()).rank
    assert a > b


def test_duplicates_rejected():
    with pytest.raises(ValueError):
        evaluate7("Ac Ac Kh 9s 7c 4d 2h".split())


def test_royal_name():
    assert evaluate7("Ah Kh Qh Jh Th 2c 3d".split()).rank.name == "Royal Flush"
