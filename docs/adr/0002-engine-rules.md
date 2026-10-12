# ADR 0002 — Engine rule choices (rules_version `nlhe-cash-1.0`)

- `raise_to` is the desired TOTAL street contribution (Appendix B).
- Minimum opening bet = big blind; minimum raise increment = last full bet/raise on the street.
- Short all-in raise (increment < last full raise) does not reopen raising for players who already
  acted. Reopening is evaluated cumulatively: a player may raise again iff
  `current_bet - level_when_they_last_acted >= last_full_raise_increment`.
- Players with no opponent able to act cannot bet/raise (call or fold only).
- Blinds are limited by stack and may be all-in; preflop amount to call is always the full BB.
- Heads-up: button posts SB and acts first preflop; BB acts first postflop.
- Uncalled bet: excess of the single top total contributor over the second-largest contribution
  (folded included) is refunded at settlement before pots are built.
- Side pots: segmented by live contribution levels; folded chips fund but are never eligible.
- Odd chips: one at a time clockwise starting from the first winner left of the button.
- Burn one card before flop, turn and river. Deck shuffled once per hand (Fisher–Yates, OS CSPRNG).
- Timeout: CHECK if legal, else FOLD.
- Leave/kick mid-hand: `force_fold` only if the player can still act (not folded, not all-in).
