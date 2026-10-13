"""Authorized, role-dependent room projections (SDD §1.2, §7 GET /rooms/{id}, §8).

Built per recipient from committed state. Never includes another player's
hidden hole cards, the deck, burned cards, invite token or password hash.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.poker import HandState, project_hand
from app.persistence.models import (
    ChipLedger,
    Guest,
    Hand,
    HandEvent,
    HandPlayer,
    Room,
    RoomMember,
    TableSeat,
    TopupRequest,
)
from app.services.secrets import get_cipher
from app.services.table import live_hand, load_state, seat_members


@dataclass
class RoomBundle:
    room: Room
    members: list[tuple[RoomMember, str]]
    seats: list[TableSeat]
    hand: Hand | None
    state: HandState | None
    topups: list[TopupRequest]
    last_result: dict[str, Any] | None = None
    # member_id -> {"in": buy-ins + top-ups, "out": cash-outs}
    ledger: dict[uuid.UUID, dict[str, int]] | None = None
    # last finished hand: seat -> (member_id, encrypted hole cards)
    last_players: dict[int, tuple[uuid.UUID, bytes]] | None = None


async def load_bundle(db: AsyncSession, room_id: uuid.UUID) -> RoomBundle | None:
    room = await db.get(Room, room_id)
    if room is None:
        return None
    members = [
        (m, nick)
        for m, nick in (
            await db.execute(
                select(RoomMember, Guest.nickname)
                .join(Guest, Guest.guest_id == RoomMember.guest_id)
                .where(RoomMember.room_id == room_id)
                .order_by(RoomMember.joined_at)
            )
        ).all()
    ]
    seats = list(
        (
            await db.scalars(
                select(TableSeat).where(TableSeat.room_id == room_id).order_by(TableSeat.seat_no)
            )
        ).all()
    )
    hand = await live_hand(db, room_id)
    state = load_state(hand) if hand is not None else None
    topups = list(
        (
            await db.scalars(
                select(TopupRequest).where(
                    TopupRequest.room_id == room_id,
                    TopupRequest.status.in_(("REQUESTED", "APPROVED")),
                )
            )
        ).all()
    )
    last_result = None
    last_players = None
    if hand is None:
        last = await db.scalar(
            select(Hand)
            .where(Hand.room_id == room_id, Hand.ended_at.is_not(None))
            .order_by(Hand.ordinal.desc())
            .limit(1)
        )
        if last is not None:
            evs = (
                await db.scalars(
                    select(HandEvent)
                    .where(
                        HandEvent.hand_id == last.id,
                        HandEvent.event_type.in_(("hand.showdown", "hand.completed")),
                    )
                    .order_by(HandEvent.seq)
                )
            ).all()
            last_result = {
                "hand_id": str(last.id),
                "ordinal": last.ordinal,
                "ended_at": last.ended_at.isoformat() if last.ended_at else None,
                **{e.event_type.split(".")[1]: e.public_payload for e in evs},
            }
            last_players = {
                hp.seat_no: (hp.member_id, hp.hole_cards_ciphertext)
                for hp in (
                    await db.scalars(select(HandPlayer).where(HandPlayer.hand_id == last.id))
                ).all()
            }
    ledger: dict[uuid.UUID, dict[str, int]] = {}
    for member_id, typ, total in (
        await db.execute(
            select(ChipLedger.member_id, ChipLedger.type, func.sum(ChipLedger.amount))
            .where(ChipLedger.room_id == room_id)
            .group_by(ChipLedger.member_id, ChipLedger.type)
        )
    ).all():
        row = ledger.setdefault(member_id, {"in": 0, "out": 0})
        if typ in ("BUY_IN", "TOP_UP"):
            row["in"] += int(total)
        elif typ == "CASH_OUT":
            row["out"] += int(total)
    return RoomBundle(room, members, seats, hand, state, topups, last_result, ledger, last_players)


def render(b: RoomBundle, viewer: RoomMember | None, connected: set[uuid.UUID]) -> dict[str, Any]:
    room = b.room
    nick = {m.id: n for m, n in b.members}
    is_host = viewer is not None and room.host_member_id == viewer.id
    my_seat = next((s for s in b.seats if viewer is not None and s.member_id == viewer.id), None)
    ledger = b.ledger or {}
    # chips committed to the live pot still count as the player's (net = at hand start)
    committed: dict[int, int] = {}
    if b.hand is not None and b.state is not None:
        committed = {n: p.total_contribution for n, p in b.state.players.items()}
    seated = {s.member_id: s for s in b.seats}

    def net_of(member_id: uuid.UUID) -> dict[str, int]:
        row = ledger.get(member_id, {"in": 0, "out": 0})
        seat = seated.get(member_id)
        stack = (seat.stack + committed.get(seat.seat_no, 0)) if seat else 0
        return {
            "invested": row["in"],
            "cashed_out": row["out"],
            "stack": stack,
            "net": stack + row["out"] - row["in"],
        }

    view: dict[str, Any] = {
        "room_id": str(room.id),
        "name": room.name,
        "status": room.status,
        "operational_status": room.operational_status,
        "auto_deal": room.auto_deal,
        "next_hand_at": room.next_hand_at.isoformat() if room.next_hand_at else None,
        "room_version": room.version,
        "config": room.config_json,
        "pending_config": room.pending_config_json,
        "host_member_id": str(room.host_member_id) if room.host_member_id else None,
        "members": [
            {
                "member_id": str(m.id),
                "nickname": n,
                "connected": m.id in connected,
                "is_host": m.id == room.host_member_id,
                "banned": m.ban_at is not None,
            }
            for m, n in b.members
            if m.ban_at is None or is_host
        ],
        "seats": [
            {
                "seat_no": s.seat_no,
                "member_id": str(s.member_id),
                "nickname": nick.get(s.member_id),
                "stack": s.stack,
                "participation_state": s.participation_state,
                "pending_leave": s.pending_leave,
                "sit_out_next": s.sit_out_next,
                "connected": s.member_id in connected,
                "net": net_of(s.member_id)["net"],
            }
            for s in b.seats
        ],
        "standings": sorted(
            (
                {"member_id": str(m.id), "nickname": n, "seated": m.id in seated, **net_of(m.id)}
                for m, n in b.members
                if m.id in ledger
            ),
            key=lambda r: -r["net"],
        ),
        "me": None,
        "hand": None,
    }
    if viewer is not None:
        view["me"] = {
            "member_id": str(viewer.id),
            "is_host": is_host,
            "seat_no": my_seat.seat_no if my_seat else None,
            "topups": [
                {"request_id": str(t.id), "amount": t.amount, "status": t.status}
                for t in b.topups
                if t.member_id == viewer.id
            ],
        }
        if is_host:
            view["pending_topups"] = [
                {
                    "request_id": str(t.id),
                    "member_id": str(t.member_id),
                    "nickname": nick.get(t.member_id),
                    "amount": t.amount,
                    "status": t.status,
                }
                for t in b.topups
                if t.status == "REQUESTED"
            ]
    if b.hand is not None and b.state is not None:
        members = seat_members(b.hand)
        viewer_seat = None
        if viewer is not None:
            viewer_seat = next((s for s, m in members.items() if m == viewer.id), None)
        hv = project_hand(b.state, viewer_seat)
        hv.update(
            {
                "hand_id": str(b.hand.id),
                "ordinal": b.hand.ordinal,
                "deadline_at": b.hand.deadline_at.isoformat() if b.hand.deadline_at else None,
            }
        )
        view["hand"] = hv
    last = dict(b.last_result) if b.last_result is not None else None
    if last is not None:
        lp = b.last_players or {}
        last["seat_members"] = {str(n): str(m) for n, (m, _) in lp.items()}
        mine = next(
            ((n, ct) for n, (m, ct) in lp.items() if viewer is not None and m == viewer.id),
            None,
        )
        # the viewer always sees their own cards in the result (public data otherwise)
        if mine is not None:
            n, ct = mine
            hand_id = uuid.UUID(last["hand_id"])
            last["my_seat"] = n
            last["my_cards"] = get_cipher().decrypt_json(ct, aad=hand_id.bytes + bytes([n]))
    view["last_hand"] = last  # public showdown/settlement + viewer's own cards
    return view
