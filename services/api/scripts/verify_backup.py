"""Verify a (restored) database: hand snapshots + chip ledger invariants (SDD §12).

    POKER_DATABASE_URL=... POKER_DATA_ENCRYPTION_KEY=... python scripts/verify_backup.py

Checks, per room:
  * ledger conservation: BUY_IN + TOP_UP - CASH_OUT == seated stacks + live pot
  * every hand snapshot decrypts with the current key and passes engine invariants
    (no negative chips, 52 unique cards, chip conservation inside the hand)
  * hand_events sequence numbers are contiguous from 1; finished hands are
    HAND_COMPLETE with a hand.completed event whose payouts equal the pot
  * at most one unfinished hand per room
Exit code 0 = healthy, 1 = problems found (details printed as JSON).
"""

from __future__ import annotations

import asyncio
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select  # noqa: E402

from app.domain.poker import Phase, assert_invariants  # noqa: E402
from app.persistence.db import dispose_engine, init_engine, new_session  # noqa: E402
from app.persistence.models import ChipLedger, Hand, HandEvent, Room, TableSeat  # noqa: E402
from app.services.table import load_state  # noqa: E402


async def verify() -> dict:
    init_engine()
    problems: list[str] = []
    stats = defaultdict(int)
    async with new_session() as db:
        rooms = (await db.scalars(select(Room))).all()
        for room in rooms:
            stats["rooms"] += 1
            ledger = dict(
                (
                    await db.execute(
                        select(ChipLedger.type, func.coalesce(func.sum(ChipLedger.amount), 0))
                        .where(ChipLedger.room_id == room.id)
                        .group_by(ChipLedger.type)
                    )
                ).all()
            )
            net = (
                ledger.get("BUY_IN", 0)
                + ledger.get("TOP_UP", 0)
                - ledger.get("CASH_OUT", 0)
                + ledger.get("CORRECTION", 0)
            )
            stacks = await db.scalar(
                select(func.coalesce(func.sum(TableSeat.stack), 0)).where(
                    TableSeat.room_id == room.id
                )
            )
            hands = (
                await db.scalars(select(Hand).where(Hand.room_id == room.id).order_by(Hand.ordinal))
            ).all()
            live = [h for h in hands if h.ended_at is None]
            if len(live) > 1:
                problems.append(f"room {room.id}: {len(live)} unfinished hands")
            pot = 0
            for h in hands:
                stats["hands"] += 1
                try:
                    st = load_state(h)
                except Exception as e:  # wrong key or corrupted blob
                    problems.append(f"hand {h.id}: snapshot does not decrypt ({type(e).__name__})")
                    continue
                try:
                    assert_invariants(st)
                except AssertionError as e:
                    problems.append(f"hand {h.id}: invariant failed: {e}")
                seqs = (
                    await db.scalars(
                        select(HandEvent.seq)
                        .where(HandEvent.hand_id == h.id)
                        .order_by(HandEvent.seq)
                    )
                ).all()
                stats["events"] += len(seqs)
                if list(seqs) != list(range(1, len(seqs) + 1)):
                    problems.append(f"hand {h.id}: event sequence has gaps")
                if h.ended_at is None:
                    pot += st.pot_total()
                    continue
                if st.phase != Phase.HAND_COMPLETE:
                    problems.append(f"hand {h.id}: ended but phase {st.phase.value}")
                done = await db.scalar(
                    select(HandEvent).where(
                        HandEvent.hand_id == h.id, HandEvent.event_type == "hand.completed"
                    )
                )
                if done is None:
                    problems.append(f"hand {h.id}: missing hand.completed event")
                elif sum(done.public_payload["payouts"].values()) != st.pot_total():
                    problems.append(f"hand {h.id}: payouts != pot")
            if net != stacks + pot:
                problems.append(f"room {room.id}: ledger net {net} != stacks {stacks} + pot {pot}")
    await dispose_engine()
    return {"ok": not problems, "stats": dict(stats), "problems": problems}


if __name__ == "__main__":
    report = asyncio.run(verify())
    print(json.dumps(report, indent=2))
    raise SystemExit(0 if report["ok"] else 1)
