"""Room service: creation, invitation+password join, host controls, bans,
top-up requests, config, presence, host election and empty-room closure."""

from __future__ import annotations

import asyncio
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select

from app.config import get_settings
from app.persistence.db import new_session
from app.persistence.models import (
    ChipLedger,
    Guest,
    Room,
    RoomBan,
    RoomMember,
    TableSeat,
    TopupRequest,
)
from app.security.passwords import hash_password, verify_password
from app.security.ratelimit import password_guess_limiter
from app.security.tokens import hash_token, new_token, tokens_equal
from app.services import clock
from app.services.errors import ServiceError
from app.services.table import (
    MAX_CHIPS,
    _cash_out,
    apply_approved_topups,
    live_hand,
    member_of,
    remove_from_table,
    require_host,
    require_open,
    seat_members,
    seat_of,
)
from app.services.uow import room_tx

CONFIG_KEYS = ("sb", "bb", "min_buyin", "max_buyin")


def validate_config(cfg: dict[str, Any]) -> dict[str, int]:
    out: dict[str, int] = {}
    for k in CONFIG_KEYS:
        v = cfg.get(k)
        if not isinstance(v, int) or isinstance(v, bool) or not 0 < v <= MAX_CHIPS:
            raise ServiceError("VALIDATION_ERROR", f"{k} must be a positive integer.")
        out[k] = v
    if out["sb"] >= out["bb"]:
        raise ServiceError("VALIDATION_ERROR", "Small blind must be less than big blind.")
    if out["min_buyin"] > out["max_buyin"]:
        raise ServiceError("VALIDATION_ERROR", "min_buyin must be <= max_buyin.")
    if out["min_buyin"] < out["bb"]:
        raise ServiceError("VALIDATION_ERROR", "min_buyin must be at least one big blind.")
    return out


# ---------------------------------------------------------------------------
# create / join
# ---------------------------------------------------------------------------
async def create_room(
    guest_id: uuid.UUID, *, password: str, name: str | None, config: dict[str, Any]
) -> dict:
    cfg = validate_config(config)
    try:
        pw_hash = await asyncio.to_thread(hash_password, password)
    except ValueError as e:
        raise ServiceError("VALIDATION_ERROR", str(e)) from None
    invite = new_token()
    room_id, member_id = uuid.uuid4(), uuid.uuid4()
    async with new_session() as db, db.begin():
        db.add(
            Room(
                id=room_id,
                name=(name or "").strip()[:64] or None,
                invite_token_hash=hash_token(invite),
                password_hash=pw_hash,
                status="OPEN",
                operational_status="ACTIVE",
                config_json=cfg,
                version=0,
            )
        )
        await db.flush()
        now = clock.now()
        db.add(
            RoomMember(
                id=member_id, room_id=room_id, guest_id=guest_id, role="member", joined_at=now
            )
        )
        await db.flush()
        room = await db.get(Room, room_id)
        assert room is not None
        room.host_member_id = member_id
        room.version = 1
    return {
        "room_id": str(room_id),
        "member_id": str(member_id),
        "invite_token": invite,
        "invite_path": f"/join/{room_id}?invite={invite}",
        "room_version": 1,
    }


async def join_room(
    room_id: uuid.UUID,
    guest_id: uuid.UUID,
    *,
    invite_token: str,
    password: str,
    client_ip: str = "?",
) -> dict:
    # rate-limit failed guesses per guest+room and per IP+room (SDD §3)
    keys = (f"g:{guest_id}:{room_id}", f"ip:{client_ip}:{room_id}")
    if any(password_guess_limiter.blocked(k) for k in keys):
        raise ServiceError("RATE_LIMITED", "Too many failed attempts; try again later.")
    # Credential checks run OUTSIDE the room lock: Argon2 is deliberately slow and
    # must not stall gameplay serialization for everyone else in the room.
    async with new_session() as db:
        room = await db.get(Room, room_id)
        if room is None:
            raise ServiceError("NOT_FOUND", "Room not found.")
        require_open(room)
        token_ok = tokens_equal(hash_token(invite_token or ""), room.invite_token_hash)
        pw_hash = room.password_hash
    if not token_ok:
        for k in keys:
            password_guess_limiter.penalize(k)
        raise ServiceError("UNAUTHORIZED", "Invalid invitation link.")
    if not await asyncio.to_thread(verify_password, pw_hash, password or ""):
        for k in keys:
            password_guess_limiter.penalize(k)
        raise ServiceError("INVALID_PASSWORD", "Wrong room password.")

    async with room_tx(room_id) as tx:
        room = tx.room
        require_open(room)
        if room.invite_token_hash != hash_token(invite_token or ""):
            raise ServiceError("UNAUTHORIZED", "Invalid invitation link.")  # rotated meanwhile
        ban = await tx.db.scalar(
            select(RoomBan).where(
                RoomBan.room_id == room_id,
                RoomBan.guest_id == guest_id,
                RoomBan.revoked_at.is_(None),
            )
        )
        if ban is not None:
            raise ServiceError("ROOM_BANNED", "You are banned from this room.")
        m = await tx.db.scalar(
            select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.guest_id == guest_id)
        )
        if m is None:
            m = RoomMember(
                id=uuid.uuid4(),
                room_id=room_id,
                guest_id=guest_id,
                role="member",
                joined_at=clock.now(),
            )
            tx.db.add(m)
            await tx.db.flush()
            nick = await tx.db.scalar(select(Guest.nickname).where(Guest.guest_id == guest_id))
            tx.bump()
            tx.emit("member.joined", {"member_id": str(m.id), "nickname": nick})
        return {"room_id": str(room_id), "member_id": str(m.id), "room_version": room.version}


# ---------------------------------------------------------------------------
# host controls
# ---------------------------------------------------------------------------
async def update_config(room_id: uuid.UUID, guest_id: uuid.UUID, patch: dict[str, Any]) -> dict:
    async with room_tx(room_id) as tx:
        member = await member_of(tx.db, room_id, guest_id)
        require_host(tx.room, member)
        require_open(tx.room)
        base = {**tx.room.config_json, **(tx.room.pending_config_json or {})}
        merged = validate_config({**base, **{k: v for k, v in patch.items() if k in CONFIG_KEYS}})
        if await live_hand(tx.db, room_id) is None:
            tx.room.config_json, tx.room.pending_config_json = merged, None
            applied = True
        else:
            tx.room.pending_config_json = merged  # takes effect at next Start Hand
            applied = False
        v = tx.bump()
        tx.emit("room.config", {"config": merged, "applied": applied})
        return {"config": merged, "applied_now": applied, "room_version": v}


async def rotate_invite(room_id: uuid.UUID, guest_id: uuid.UUID) -> dict:
    """Host issues a new invitation token; the previous link stops working."""
    async with room_tx(room_id) as tx:
        member = await member_of(tx.db, room_id, guest_id)
        require_host(tx.room, member)
        require_open(tx.room)
        invite = new_token()
        tx.room.invite_token_hash = hash_token(invite)
        v = tx.bump()
        return {
            "invite_token": invite,
            "invite_path": f"/join/{room_id}?invite={invite}",
            "room_version": v,
        }


async def transfer_host(room_id: uuid.UUID, guest_id: uuid.UUID, target: uuid.UUID) -> dict:
    async with room_tx(room_id) as tx:
        member = await member_of(tx.db, room_id, guest_id)
        require_host(tx.room, member)
        t = await tx.db.get(RoomMember, target)
        if t is None or t.room_id != room_id or t.ban_at is not None:
            raise ServiceError(
                "INVALID_ACTION", "Target must be an active room member.", tx.room.version
            )
        tx.room.host_member_id = t.id
        v = tx.bump()
        tx.emit("room.host_changed", {"host_member_id": str(t.id), "reason": "TRANSFER"})
        return {"host_member_id": str(t.id), "room_version": v}


async def kick(room_id: uuid.UUID, guest_id: uuid.UUID, target: uuid.UUID, *, ban: bool) -> dict:
    async with room_tx(room_id) as tx:
        member = await member_of(tx.db, room_id, guest_id)
        require_host(tx.room, member)
        t = await tx.db.get(RoomMember, target)
        if t is None or t.room_id != room_id:
            raise ServiceError("NOT_FOUND", "Member not found.", tx.room.version)
        if t.id == member.id:
            raise ServiceError("INVALID_ACTION", "Host cannot kick themselves.", tx.room.version)
        if ban:
            active = await tx.db.scalar(
                select(RoomBan).where(
                    RoomBan.room_id == room_id,
                    RoomBan.guest_id == t.guest_id,
                    RoomBan.revoked_at.is_(None),
                )
            )
            if active is None:
                tx.db.add(
                    RoomBan(
                        id=uuid.uuid4(), room_id=room_id, guest_id=t.guest_id, banned_by=member.id
                    )
                )
            t.ban_at = clock.now()
        status = await remove_from_table(tx, t.id)
        if ban:
            tx.removed_members.append(t.id)
        v = tx.bump()
        tx.emit(
            "member.banned" if ban else "member.kicked",
            {"member_id": str(t.id), "seat_status": status},
        )
        return {"member_id": str(t.id), "banned": ban, "seat_status": status, "room_version": v}


async def unban(room_id: uuid.UUID, guest_id: uuid.UUID, target: uuid.UUID) -> dict:
    async with room_tx(room_id) as tx:
        member = await member_of(tx.db, room_id, guest_id)
        require_host(tx.room, member)  # replaced host inherits ban permissions
        t = await tx.db.get(RoomMember, target)
        if t is None or t.room_id != room_id:
            raise ServiceError("NOT_FOUND", "Member not found.", tx.room.version)
        bans = (
            await tx.db.scalars(
                select(RoomBan).where(
                    RoomBan.room_id == room_id,
                    RoomBan.guest_id == t.guest_id,
                    RoomBan.revoked_at.is_(None),
                )
            )
        ).all()
        for b in bans:
            b.revoked_at = clock.now()
        t.ban_at = None
        v = tx.bump()
        tx.emit("member.unbanned", {"member_id": str(t.id)})
        return {"member_id": str(t.id), "banned": False, "room_version": v}


# ---------------------------------------------------------------------------
# top-ups (SDD §5.4): request -> host approve -> applied between hands
# ---------------------------------------------------------------------------
async def request_topup(room_id: uuid.UUID, guest_id: uuid.UUID, amount: int) -> dict:
    async with room_tx(room_id) as tx:
        member = await member_of(tx.db, room_id, guest_id)
        seat = await seat_of(tx.db, room_id, member.id)
        if seat is None:
            raise ServiceError("INVALID_ACTION", "Sit down first.", tx.room.version)
        if not isinstance(amount, int) or isinstance(amount, bool) or amount <= 0:
            raise ServiceError("VALIDATION_ERROR", "Amount must be a positive integer.")
        pending = sum(
            (
                await tx.db.scalars(
                    select(TopupRequest.amount).where(
                        TopupRequest.room_id == room_id,
                        TopupRequest.member_id == member.id,
                        TopupRequest.status.in_(("REQUESTED", "APPROVED")),
                    )
                )
            ).all()
        )
        if seat.stack + pending + amount > tx.room.config_json["max_buyin"]:
            raise ServiceError(
                "TOPUP_LIMIT_EXCEEDED", "Would exceed the max buy-in.", tx.room.version
            )
        r = TopupRequest(
            id=uuid.uuid4(), room_id=room_id, member_id=member.id, amount=amount, status="REQUESTED"
        )
        tx.db.add(r)
        v = tx.bump()
        tx.emit(
            "chip.requested", {"request_id": str(r.id), "seat_no": seat.seat_no, "amount": amount}
        )
        return {"request_id": str(r.id), "status": "REQUESTED", "room_version": v}


async def decide_topup(
    room_id: uuid.UUID, guest_id: uuid.UUID, request_id: uuid.UUID, approve: bool
) -> dict:
    async with room_tx(room_id) as tx:
        member = await member_of(tx.db, room_id, guest_id)
        require_host(tx.room, member)
        r = await tx.db.get(TopupRequest, request_id)
        if r is None or r.room_id != room_id:
            raise ServiceError("NOT_FOUND", "Request not found.", tx.room.version)
        if r.status != "REQUESTED":
            raise ServiceError("INVALID_ACTION", f"Request already {r.status}.", tx.room.version)
        r.status = "APPROVED" if approve else "REJECTED"
        r.approved_by = member.id if approve else None
        if approve:
            tx.emit("chip.approved", {"request_id": str(r.id), "amount": r.amount})
            if await live_hand(tx.db, room_id) is None:
                await apply_approved_topups(tx)  # already between hands
        v = tx.bump()
        await tx.db.flush()
        return {"request_id": str(r.id), "status": r.status, "room_version": v}


# ---------------------------------------------------------------------------
# presence, host election (SDD §3) and closure (SDD §4)
# ---------------------------------------------------------------------------
async def _elect(tx, connected: set[uuid.UUID], exclude: uuid.UUID | None) -> bool:
    cands = (
        await tx.db.scalars(
            select(RoomMember)
            .where(RoomMember.room_id == tx.room.id, RoomMember.ban_at.is_(None))
            .order_by(RoomMember.joined_at, RoomMember.id)
        )
    ).all()
    for c in cands:
        if c.id in connected and c.id != exclude:
            tx.room.host_member_id = c.id
            tx.bump()
            tx.emit("room.host_changed", {"host_member_id": str(c.id), "reason": "ELECTION"})
            return True
    return False


async def on_connect(room_id: uuid.UUID, member_id: uuid.UUID, connected: set[uuid.UUID]) -> None:
    async with room_tx(room_id) as tx:
        m = await tx.db.get(RoomMember, member_id)
        if m is None:
            return
        m.last_connected_at, m.disconnected_since = clock.now(), None
        if tx.room.status == "EMPTY_PENDING_CLOSE":
            tx.room.status, tx.room.empty_since = "OPEN", None
            tx.bump()
        if tx.room.host_member_id is None:
            await _elect(tx, connected, exclude=None)
        tx.emit("presence", {"member_id": str(member_id), "connected": True})
        tx.changed = True


async def on_disconnect(
    room_id: uuid.UUID, member_id: uuid.UUID, connected: set[uuid.UUID]
) -> None:
    async with room_tx(room_id) as tx:
        m = await tx.db.get(RoomMember, member_id)
        if m is None:
            return
        if member_id not in connected:
            m.disconnected_since = clock.now()
        if not connected and tx.room.status == "OPEN":
            tx.room.status, tx.room.empty_since = "EMPTY_PENDING_CLOSE", clock.now()
            tx.bump()
        tx.emit("presence", {"member_id": str(member_id), "connected": False})
        tx.changed = True


async def sweep_room(room_id: uuid.UUID, connected: set[uuid.UUID]) -> None:
    """Periodic idempotent job: host election after grace; 24 h empty closure."""
    s = get_settings()
    async with room_tx(room_id) as tx:
        room, now = tx.room, clock.now()
        if room.status == "CLOSED":
            return
        if room.host_member_id is not None:
            host = await tx.db.get(RoomMember, room.host_member_id)
            gone = (
                host is None
                or host.ban_at is not None
                or (
                    host.id not in connected
                    and host.disconnected_since is not None
                    and now - host.disconnected_since
                    >= timedelta(seconds=s.host_disconnect_grace_seconds)
                )
            )
            if gone:
                await _elect(tx, connected, exclude=room.host_member_id)
        elif connected:
            await _elect(tx, connected, exclude=None)
        # stand up players who have been sitting out too long (seat freed, chips to ledger)
        cutoff = now - timedelta(minutes=s.sit_out_stand_up_minutes)
        idle = (
            await tx.db.scalars(
                select(TableSeat).where(
                    TableSeat.room_id == room_id,
                    TableSeat.participation_state == "SITTING_OUT",
                    TableSeat.sitting_out_since.is_not(None),
                    TableSeat.sitting_out_since <= cutoff,
                )
            )
        ).all()
        if idle:
            hand = await live_hand(tx.db, room_id)
            in_hand = set(seat_members(hand)) if hand is not None else set()
            for seat in idle:
                if seat.seat_no in in_hand:
                    continue
                await _cash_out(tx, seat)
                tx.emit("player.stood_up", {"seat_no": seat.seat_no, "reason": "SIT_OUT_TIMEOUT"})
                tx.bump()
        if (
            room.status == "EMPTY_PENDING_CLOSE"
            and room.empty_since is not None
            and now - room.empty_since >= timedelta(hours=s.empty_room_close_hours)
        ):
            if await live_hand(tx.db, room_id) is not None:
                # never silently discard a live pot: leave paused for operator (A-10)
                if room.operational_status != "PAUSED_RECOVERY":
                    room.operational_status = "PAUSED_RECOVERY"
                    tx.bump()
                return
            seats = (
                await tx.db.scalars(select(TableSeat).where(TableSeat.room_id == room_id))
            ).all()
            for seat in seats:
                await _cash_out(tx, seat)  # archive: ledger closes out every stack
            room.status, room.closed_at = "CLOSED", now
            tx.bump()
            tx.emit("room.closed", {})


# ---------------------------------------------------------------------------
# queries
# ---------------------------------------------------------------------------
async def my_rooms(guest_id: uuid.UUID) -> list[dict]:
    async with new_session() as db:
        rows = (
            await db.execute(
                select(RoomMember, Room)
                .join(Room, Room.id == RoomMember.room_id)
                .where(RoomMember.guest_id == guest_id)
                .order_by(RoomMember.joined_at.desc())
            )
        ).all()
        return [
            {
                "room_id": str(r.id),
                "name": r.name,
                "status": r.status,
                "member_id": str(m.id),
                "is_host": r.host_member_id == m.id,
                "banned": m.ban_at is not None,
            }
            for m, r in rows
        ]


async def ledger_view(room_id: uuid.UUID, guest_id: uuid.UUID) -> dict:
    """Room members see the room ledger; banned members see only their own (A-03)."""
    async with new_session() as db:
        member = await member_of(db, room_id, guest_id, allow_banned=True)
        q = select(ChipLedger).where(ChipLedger.room_id == room_id)
        if member.ban_at is not None:
            q = q.where(ChipLedger.member_id == member.id)
        entries = (await db.scalars(q.order_by(ChipLedger.created_at, ChipLedger.id))).all()
        seats = {
            s.member_id: s.stack
            for s in (await db.scalars(select(TableSeat).where(TableSeat.room_id == room_id))).all()
        }
        summary: dict[uuid.UUID, dict[str, int]] = {}
        for e in entries:
            row = summary.setdefault(
                e.member_id, {"BUY_IN": 0, "TOP_UP": 0, "CASH_OUT": 0, "CORRECTION": 0}
            )
            row[e.type] += e.amount
        out_summary = []
        for mid, row in summary.items():
            stack = seats.get(mid, 0)
            out_summary.append(
                {
                    "member_id": str(mid),
                    "total_buyins": row["BUY_IN"],
                    "total_topups": row["TOP_UP"],
                    "cash_out": row["CASH_OUT"],
                    "current_stack": stack,
                    # SDD §5.4: net = cash_out + current_stack - total_buyins - total_topups
                    "net": row["CASH_OUT"] + stack - row["BUY_IN"] - row["TOP_UP"],
                }
            )
        return {
            "entries": [
                {
                    "id": str(e.id),
                    "member_id": str(e.member_id),
                    "type": e.type,
                    "amount": e.amount,
                    "created_at": e.created_at.isoformat(),
                }
                for e in entries
            ],
            "summary": out_summary,
        }
