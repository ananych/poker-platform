"""Hand state model (pure data). Serializable to/from plain dicts for durable
snapshots (SDD §6.1). Private fields (deck, hole cards) must be encrypted by the
persistence layer and never sent to clients unredacted.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any

RULES_VERSION = "nlhe-cash-1.0"
MAX_SEATS = 9


class Phase(str, Enum):
    WAITING_FOR_HOST = "WAITING_FOR_HOST"
    HAND_SETUP = "HAND_SETUP"
    PREFLOP = "PREFLOP"
    FLOP = "FLOP"
    TURN = "TURN"
    RIVER = "RIVER"
    SHOWDOWN = "SHOWDOWN"
    SETTLEMENT = "SETTLEMENT"
    HAND_COMPLETE = "HAND_COMPLETE"


BETTING_PHASES = (Phase.PREFLOP, Phase.FLOP, Phase.TURN, Phase.RIVER)


class ActionType(str, Enum):
    FOLD = "FOLD"
    CHECK = "CHECK"
    CALL = "CALL"
    BET = "BET"
    RAISE = "RAISE"
    ALL_IN = "ALL_IN"


class ShowStatus(str, Enum):
    HIDDEN = "HIDDEN"
    SHOWN = "SHOWN"
    MUCKED = "MUCKED"


@dataclass(frozen=True)
class HandConfig:
    """Frozen config snapshot copied into each hand (SDD §4)."""

    small_blind: int
    big_blind: int
    rules_version: str = RULES_VERSION
    max_seats: int = MAX_SEATS

    def validate(self) -> None:
        if not (isinstance(self.small_blind, int) and isinstance(self.big_blind, int)):
            raise ValueError("blinds must be integers")
        if self.small_blind <= 0 or self.big_blind <= 0:
            raise ValueError("blinds must be positive")
        if self.small_blind >= self.big_blind:
            raise ValueError("small blind must be < big blind")


@dataclass
class PlayerState:
    seat: int
    stack: int  # chips behind (not yet committed)
    hole_cards: list[str] = field(default_factory=list)
    street_contribution: int = 0
    total_contribution: int = 0
    folded: bool = False
    all_in: bool = False
    acted_this_street: bool = False
    # current_bet level at the time of this player's last voluntary action on
    # this street; used to decide whether a later (possibly cumulative short)
    # raise re-opens raising rights for this player.
    bet_faced_when_acted: int = 0
    show_status: ShowStatus = ShowStatus.HIDDEN

    @property
    def can_act(self) -> bool:
        return not self.folded and not self.all_in


@dataclass
class HandResult:
    payouts: dict[int, int]  # seat -> chips awarded (incl. refunds)
    refunds: dict[int, int]
    pots: list[dict[str, Any]]
    hands: dict[int, dict[str, Any]]  # seat -> {rank, name, best_five} for shown hands


@dataclass
class HandState:
    config: HandConfig
    button_seat: int
    sb_seat: int
    bb_seat: int
    players: dict[int, PlayerState]
    deck: list[str]  # remaining undealt cards (PRIVATE)
    phase: Phase = Phase.HAND_SETUP
    board: list[str] = field(default_factory=list)
    burned: list[str] = field(default_factory=list)  # PRIVATE
    actor_seat: int | None = None
    current_bet: int = 0
    min_raise_increment: int = 0  # last full bet/raise size on this street
    last_aggressor_seat: int | None = None
    seq: int = 0  # monotonic event sequence within the hand
    starting_total: int = 0  # conservation reference
    result: HandResult | None = None

    # ---- helpers -------------------------------------------------------
    def seats_in_order(self) -> list[int]:
        return sorted(self.players)

    def live_seats(self) -> list[int]:
        return [s for s in self.seats_in_order() if not self.players[s].folded]

    def actionable_seats(self) -> list[int]:
        return [s for s in self.seats_in_order() if self.players[s].can_act]

    def pot_total(self) -> int:
        return sum(p.total_contribution for p in self.players.values())

    def to_dict(self) -> dict[str, Any]:
        """JSON-safe dict (int keys become strings). Contains PRIVATE data."""
        d = asdict(self)
        d["phase"] = self.phase.value
        d["players"] = {
            str(s): {**pd, "show_status": ShowStatus(pd["show_status"]).value}
            for s, pd in d["players"].items()
        }
        if d["result"] is not None:
            r = d["result"]
            r["payouts"] = {str(k): v for k, v in r["payouts"].items()}
            r["refunds"] = {str(k): v for k, v in r["refunds"].items()}
            r["hands"] = {str(k): v for k, v in r["hands"].items()}
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> HandState:
        players = {
            int(s): PlayerState(**{**pd, "show_status": ShowStatus(pd["show_status"])})
            for s, pd in d["players"].items()
        }
        result = None
        if d.get("result") is not None:
            r = d["result"]
            result = HandResult(
                payouts={int(k): v for k, v in r["payouts"].items()},
                refunds={int(k): v for k, v in r["refunds"].items()},
                pots=r["pots"],
                hands={int(k): v for k, v in r["hands"].items()},
            )
        fields = {k: v for k, v in d.items() if k not in ("config", "players", "result", "phase")}
        return cls(
            config=HandConfig(**d["config"]),
            players=players,
            phase=Phase(d["phase"]),
            result=result,
            **fields,
        )


@dataclass(frozen=True)
class LegalActions:
    seat: int
    can_fold: bool
    can_check: bool
    call_amount: int  # chips added by calling (0 if cannot call)
    can_bet: bool
    can_raise: bool
    min_raise_to: int  # min legal total street contribution for bet/raise
    max_raise_to: int  # all-in total street contribution

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
