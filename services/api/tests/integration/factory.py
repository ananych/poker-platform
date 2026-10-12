"""Service-level helpers for integration tests (bypass HTTP for speed)."""

from __future__ import annotations

import random
import uuid
from datetime import timedelta

from sqlalchemy import func, select

from app.persistence.db import new_session
from app.persistence.models import ChipLedger, Hand, RoomMember, TableSeat
from app.services import rooms, table
from app.services.guests import create_guest_session
from app.services.views import load_bundle, render

PASSWORD = "secret-pass"


async def make_guest(nick: str = "p") -> uuid.UUID:
    async with new_session() as db, db.begin():
        ctx, _ = await create_guest_session(db, nick, timedelta(days=1))
        return ctx.guest.guest_id


async def make_table(
    n: int,
    *,
    sb: int = 5,
    bb: int = 10,
    buyin: int = 1000,
    min_buyin: int = 100,
    max_buyin: int = 2000,
    seats: list[int] | None = None,
):
    """Returns (room_id, guests) where guests[0] is the host; seated at `seats`."""
    host = await make_guest("host")
    r = await rooms.create_room(
        host,
        password=PASSWORD,
        name="t",
        config={"sb": sb, "bb": bb, "min_buyin": min_buyin, "max_buyin": max_buyin},
    )
    room_id = uuid.UUID(r["room_id"])
    guests = [host]
    for i in range(1, n):
        g = await make_guest(f"p{i}")
        await rooms.join_room(
            room_id, g, invite_token=r["invite_token"], password=PASSWORD, client_ip=str(g)
        )
        guests.append(g)
    seats = seats or list(range(1, n + 1))
    for g, s in zip(guests, seats, strict=True):
        await table.claim_seat(room_id, g, s, buyin)
    return room_id, guests, r


async def view_for(room_id: uuid.UUID, guest_id: uuid.UUID) -> dict:
    async with new_session() as db:
        m = await db.scalar(
            select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.guest_id == guest_id)
        )
        b = await load_bundle(db, room_id)
        return render(b, m, set())


async def actor_guest(room_id: uuid.UUID, guests: list[uuid.UUID]) -> tuple[uuid.UUID, dict]:
    """Find whose turn it is; return (guest_id, their view)."""
    for g in guests:
        v = await view_for(room_id, g)
        h = v["hand"]
        if h and h.get("legal_actions"):
            return g, v
    raise AssertionError("no actor found")


def choose(la: dict, rng: random.Random) -> tuple[str, int | None]:
    opts: list[tuple[str, int | None]] = [("FOLD", None)]
    if la["can_check"]:
        opts += [("CHECK", None)] * 3
    if la["call_amount"] > 0:
        opts += [("CALL", None)] * 3
    if la["can_bet"]:
        opts.append(("BET", rng.randint(la["min_raise_to"], la["max_raise_to"])))
    if la["can_raise"]:
        opts.append(("RAISE", rng.randint(la["min_raise_to"], la["max_raise_to"])))
    if la["can_bet"] or la["can_raise"]:
        opts.append(("ALL_IN", None))
    return rng.choice(opts)


async def act(room_id, guest, view, action, raise_to=None, action_id=None):
    return await table.player_action(
        room_id,
        guest,
        action_id=action_id or uuid.uuid4(),
        hand_id=uuid.UUID(view["hand"]["hand_id"]),
        expected_version=view["room_version"],
        action=action,
        raise_to=raise_to,
    )


async def play_hand_randomly(room_id, guests, rng: random.Random, max_steps: int = 200) -> None:
    for _ in range(max_steps):
        v = await view_for(room_id, guests[0])
        if v["hand"] is None:
            return
        g, gv = await actor_guest(room_id, guests)
        a, amt = choose(gv["hand"]["legal_actions"], rng)
        await act(room_id, g, gv, a, amt)
    raise AssertionError("hand did not finish")


async def chip_totals(room_id: uuid.UUID) -> tuple[int, int]:
    """(ledger in - out, chips on table incl. live pot)."""
    async with new_session() as db:
        rows = dict(
            (
                await db.execute(
                    select(ChipLedger.type, func.sum(ChipLedger.amount))
                    .where(ChipLedger.room_id == room_id)
                    .group_by(ChipLedger.type)
                )
            ).all()
        )
        net = rows.get("BUY_IN", 0) + rows.get("TOP_UP", 0) - rows.get("CASH_OUT", 0)
        stacks = await db.scalar(
            select(func.coalesce(func.sum(TableSeat.stack), 0)).where(TableSeat.room_id == room_id)
        )
        hand = await db.scalar(select(Hand).where(Hand.room_id == room_id, Hand.ended_at.is_(None)))
        pot = 0
        if hand is not None:
            pot = table.load_state(hand).pot_total()
        return net, stacks + pot
