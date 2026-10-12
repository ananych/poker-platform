"""Hand history and redacted replay (SDD §10).

Replay shows only publicly observable events in sequence order. Hole cards
appear only where they became public (the `hand.showdown` event lists shown
hands); mucked/unrevealed cards are never present in public payloads. A viewer
who played the hand additionally receives their own hole cards.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select

from app.persistence.db import new_session
from app.persistence.models import Guest, Hand, HandEvent, RoomMember
from app.services.errors import ServiceError
from app.services.secrets import get_cipher
from app.services.table import member_of, seat_members

PAGE = 20


async def _nicknames(db, member_ids: list[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not member_ids:
        return {}
    rows = (
        await db.execute(
            select(RoomMember.id, Guest.nickname)
            .join(Guest, Guest.guest_id == RoomMember.guest_id)
            .where(RoomMember.id.in_(member_ids))
        )
    ).all()
    return dict(rows)


async def list_hands(
    room_id: uuid.UUID, guest_id: uuid.UUID, *, cursor: int | None = None, limit: int = PAGE
) -> dict:
    limit = max(1, min(limit, 50))
    async with new_session() as db:
        me = await member_of(db, room_id, guest_id)  # banned members: no history (A-03)
        q = select(Hand).where(Hand.room_id == room_id, Hand.ended_at.is_not(None))
        if cursor is not None:
            q = q.where(Hand.ordinal < cursor)
        hands = (await db.scalars(q.order_by(Hand.ordinal.desc()).limit(limit + 1))).all()
        more = len(hands) > limit
        hands = hands[:limit]
        completed = {}
        if hands:
            evs = (
                await db.scalars(
                    select(HandEvent).where(
                        HandEvent.hand_id.in_([h.id for h in hands]),
                        HandEvent.event_type == "hand.completed",
                    )
                )
            ).all()
            completed = {e.hand_id: e.public_payload for e in evs}
        all_members = {m for h in hands for m in seat_members(h).values()}
        nick = await _nicknames(db, list(all_members))
        items = []
        for h in hands:
            sm = seat_members(h)
            c = completed.get(h.id, {})
            my_seat = next((s for s, m in sm.items() if m == me.id), None)
            payouts = c.get("payouts", {})
            items.append(
                {
                    "hand_id": str(h.id),
                    "ordinal": h.ordinal,
                    "started_at": h.started_at.isoformat(),
                    "ended_at": h.ended_at.isoformat() if h.ended_at else None,
                    "blinds": [h.config_snapshot["sb"], h.config_snapshot["bb"]],
                    "board": c.get("board", []),
                    "pots": c.get("pots", []),
                    "uncontested": c.get("uncontested"),
                    "players": [
                        {
                            "seat_no": s,
                            "member_id": str(m),
                            "nickname": nick.get(m),
                            "won": payouts.get(str(s), 0),
                        }
                        for s, m in sorted(sm.items())
                    ],
                    "my_seat": my_seat,
                    "my_result": None if my_seat is None else payouts.get(str(my_seat), 0),
                }
            )
        return {"items": items, "next_cursor": hands[-1].ordinal if more and hands else None}


async def replay(room_id: uuid.UUID, guest_id: uuid.UUID, hand_id: uuid.UUID) -> dict:
    async with new_session() as db:
        me = await member_of(db, room_id, guest_id)
        hand = await db.get(Hand, hand_id)
        if hand is None or hand.room_id != room_id:
            raise ServiceError("NOT_FOUND", "Hand not found.")
        if hand.ended_at is None:
            raise ServiceError("HAND_ALREADY_RUNNING", "Replay is available after the hand ends.")
        sm = seat_members(hand)
        nick = await _nicknames(db, list(sm.values()))
        my_seat = next((s for s, m in sm.items() if m == me.id), None)
        events = (
            await db.scalars(
                select(HandEvent).where(HandEvent.hand_id == hand_id).order_by(HandEvent.seq)
            )
        ).all()
        out, my_cards = [], None
        for e in events:
            if e.private_to_seat is not None:
                if e.private_to_seat == my_seat and e.private_payload_ciphertext:
                    priv = get_cipher().decrypt_json(
                        e.private_payload_ciphertext, aad=hand.id.bytes + str(e.seq).encode()
                    )
                    my_cards = priv.get("hole_cards")
                continue  # never include other players' private events
            out.append(
                {
                    "seq": e.seq,
                    "type": e.event_type,
                    "payload": e.public_payload,
                    "at": e.created_at.isoformat(),
                }
            )
        return {
            "hand_id": str(hand.id),
            "ordinal": hand.ordinal,
            "config": {k: hand.config_snapshot[k] for k in ("sb", "bb", "rules_version")},
            "button_seat": hand.button_seat,
            "players": [
                {"seat_no": s, "member_id": str(m), "nickname": nick.get(m)}
                for s, m in sorted(sm.items())
            ],
            "my_seat": my_seat,
            "my_cards": my_cards,
            "events": out,
        }
