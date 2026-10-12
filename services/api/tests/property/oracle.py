"""Independent 7-card evaluator used ONLY as a test oracle.

Different algorithm from app.domain.poker.evaluator (direct count/bitmask
analysis of all 7 cards instead of best-of-21 enumeration).
"""

from collections import Counter

R = {r: i for i, r in enumerate("23456789TJQKA", start=2)}


def _straight_top(rankset):
    bits = set(rankset)
    if 14 in bits:
        bits.add(1)
    for top in range(14, 4, -1):
        if all(t in bits for t in range(top - 4, top + 1)):
            return top
    return None


def oracle_rank(cards):
    ranks = [R[c[0]] for c in cards]
    suits = Counter(c[1] for c in cards)
    flush_suit = next((s for s, n in suits.items() if n >= 5), None)
    if flush_suit:
        fr = sorted((R[c[0]] for c in cards if c[1] == flush_suit), reverse=True)
        sf = _straight_top(fr)
        if sf:
            return (8, (sf,))
    cnt = Counter(ranks)
    quads = sorted([r for r, n in cnt.items() if n == 4], reverse=True)
    trips = sorted([r for r, n in cnt.items() if n == 3], reverse=True)
    pairs = sorted([r for r, n in cnt.items() if n == 2], reverse=True)
    if quads:
        q = quads[0]
        return (7, (q, max(r for r in ranks if r != q)))
    if trips and (len(trips) >= 2 or pairs):
        t = trips[0]
        p = max(trips[1:] + pairs)
        return (6, (t, p))
    if flush_suit:
        return (5, tuple(fr[:5]))
    st = _straight_top(ranks)
    if st:
        return (4, (st,))
    desc = sorted(ranks, reverse=True)
    if trips:
        t = trips[0]
        return (3, (t, *[r for r in desc if r != t][:2]))
    if len(pairs) >= 2:
        a, b = pairs[:2]
        return (2, (a, b, max(r for r in ranks if r not in (a, b))))
    if pairs:
        p = pairs[0]
        return (1, (p, *[r for r in desc if r != p][:3]))
    return (0, tuple(desc[:5]))
