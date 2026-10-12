from hypothesis import given, settings
from hypothesis import strategies as st

from app.domain.poker.cards import FULL_DECK
from app.domain.poker.evaluator import evaluate7
from tests.property.oracle import oracle_rank

seven_cards = st.lists(st.sampled_from(FULL_DECK), min_size=7, max_size=7, unique=True)


@settings(max_examples=3000, deadline=None)
@given(seven_cards)
def test_evaluator_matches_oracle(cards):
    ev = evaluate7(cards)
    assert (int(ev.rank.category), ev.rank.tiebreak) == oracle_rank(cards)


@settings(max_examples=1000, deadline=None)
@given(st.lists(st.sampled_from(FULL_DECK), min_size=9, max_size=9, unique=True))
def test_pairwise_ordering_matches_oracle(cards):
    a, b = cards[:7], cards[2:]
    ra, rb = evaluate7(a).rank, evaluate7(b).rank
    oa, ob = oracle_rank(a), oracle_rank(b)
    assert (ra > rb) == (oa > ob) and (ra == rb) == (oa == ob)
