"""Table service: seats, buy-ins, sit-out/leave, top-up application, and the
durable hand lifecycle (start, actions, timeouts, settlement, recovery).

All mutations run inside `room_tx` (per-room mutex + row lock + version bump).
Hidden data (deck, hole cards) is stored only encrypted (SDD §5.2, §6).
"""

from __future__ import annotations

import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.domain.poker import (
    ActionType,
    EngineError,
    HandConfig,
    HandState,
    Phase,
    apply_action,
    force_fold,
    start_hand,
    timeout_action,
)
from app.domain.poker.positions import next_hand_positions
from app.domain.poker.state import BETTING_PHASES
from app.persistence.models import (
    ActionResult,
    ChipLedger,
    Hand,
    HandEvent,
    HandPlayer,
    Room,
    RoomMember,
    TableSeat,
    TopupRequest,
)
from app.services import clock
from app.services.errors import ServiceError
from app.services.metrics import metrics
from app.services.secrets import get_cipher
from app.services.timers import timers
from app.services.uow import RoomTx, room_tx

MAX_CHIPS = 10**12


class _Lifecycle:
    draining = False  # set on shutdown: refuse new hand starts (SDD §12 rolling restart)


lifecycle = _Lifecycle()


# ---------------------------------------------------------------------------
# lookups / authorization
# ---------------------------------------------------------------------------
async def member_of(
    db: AsyncSession, room_id: uuid.UUID, guest_id: uuid.UUID, *, allow_banned: bool = False
) -> RoomMember:
    m = await db.scalar(
        select(RoomMember).where(RoomMember.room_id == room_id, RoomMember.guest_id == guest_id)
    )
    if m is None:
        raise ServiceError("NOT_MEMBER", "Join the room first.")
    if m.ban_at is not None and not allow_banned:
        raise ServiceError("ROOM_BANNED", "You are banned from this room.")
    return m


def require_host(room: Room, member: RoomMember) -> None:
    if room.host_member_id != member.id:
        raise ServiceError("NOT_HOST", "Only the host may do this.", room.version)


def require_open(room: Room) -> None:
    if room.status == "CLOSED":
        raise ServiceError("ROOM_CLOSED", "Room is closed.", room.version)


def require_version(room: Room, expected: int | None) -> None:
    if expected is not None and expected != room.version:
        raise ServiceError("STALE_VERSION", "Room state changed; refresh.", room.version)


async def seat_of(db: AsyncSession, room_id: uuid.UUID, member_id: uuid.UUID) -> TableSeat | None:
    return await db.scalar(
        select(TableSeat).where(TableSeat.room_id == room_id, TableSeat.member_id == member_id)
    )


async def live_hand(db: AsyncSession, room_id: uuid.UUID) -> Hand | None:
    return await db.scalar(select(Hand).where(Hand.room_id == room_id, Hand.ended_at.is_(None)))


def load_state(hand: Hand) -> HandState:
    return HandState.from_dict(
        get_cipher().decrypt_json(hand.hand_snapshot_encrypted, aad=hand.id.bytes)
    )


def seat_members(hand: Hand) -> dict[int, uuid.UUID]:
    return {int(k): uuid.UUID(v) for k, v in hand.config_snapshot["seat_members"].items()}


def _config(room: Room) -> dict[str, int]:
    return dict(room.config_json)


# ---------------------------------------------------------------------------
# ledger helpers (SDD §5.4)
# ---------------------------------------------------------------------------
def _ledger(tx: RoomTx, member_id: uuid.UUID, typ: str, amount: int, ref: str | None = None):
    tx.db.add(
        ChipLedger(
            id=uuid.uuid4(),
            room_id=tx.room.id,
            member_id=member_id,
            type=typ,
            amount=amount,
            reference_id=ref or f"{typ.lower()}:{uuid.uuid4()}",
            applied_at=clock.now(),
        )
    )


async def _cash_out(tx: RoomTx, seat: TableSeat) -> int:
    amount = seat.stack
    _ledger(tx, seat.member_id, "CASH_OUT", amount)
    await tx.db.delete(seat)
    await tx.db.flush()
    tx.emit(
        "player.left",
        {"seat_no": seat.seat_no, "member_id": str(seat.member_id), "cash_out": amount},
    )
    return amount


async def apply_approved_topups(tx: RoomTx) -> None:
    """Apply APPROVED top-ups atomically between hands (cap = current max buy-in, A-04)."""
    cfg = _config(tx.room)
    reqs = (
        await tx.db.scalars(
            select(TopupRequest)
            .where(TopupRequest.room_id == tx.room.id, TopupRequest.status == "APPROVED")
            .order_by(TopupRequest.created_at)
        )
    ).all()
    for r in reqs:
        seat = await seat_of(tx.db, tx.room.id, r.member_id)
        if seat is None or seat.pending_leave:
            r.status = "REJECTED"
            continue
        if seat.stack + r.amount > cfg["max_buyin"]:
            r.status = "REJECTED"
            tx.emit("chip.rejected", {"request_id": str(r.id), "reason": "TOPUP_LIMIT_EXCEEDED"})
            continue
        seat.stack += r.amount
        r.status = "APPLIED"
        r.applied_at = clock.now()
        _ledger(tx, r.member_id, "TOP_UP", r.amount, ref=f"topup:{r.id}")
        tx.emit(
            "chip.applied",
            {
                "request_id": str(r.id),
                "seat_no": seat.seat_no,
                "amount": r.amount,
                "stack": seat.stack,
            },
        )


# ---------------------------------------------------------------------------
# seats
# ---------------------------------------------------------------------------
async def claim_seat(room_id: uuid.UUID, guest_id: uuid.UUID, seat_no: int, buyin: int) -> dict:
    async with room_tx(room_id) as tx:
        room = tx.room
        require_open(room)
        member = await member_of(tx.db, room_id, guest_id)
        if not 1 <= seat_no <= 9:
            raise ServiceError("INVALID_ACTION", "Seat must be 1..9.", room.version)
        if await seat_of(tx.db, room_id, member.id) is not None:
            raise ServiceError("ALREADY_SEATED", "You already have a seat.", room.version)
        taken = await tx.db.get(TableSeat, (room_id, seat_no))
        if taken is not None:
            raise ServiceError("SEAT_TAKEN", "Seat is taken.", room.version)
        cfg = _config(room)
        if (
            not isinstance(buyin, int)
            or isinstance(buyin, bool)
            or not cfg["min_buyin"] <= buyin <= cfg["max_buyin"]
        ):
            raise ServiceError(
                "INVALID_BUYIN",
                f"Buy-in must be {cfg['min_buyin']}..{cfg['max_buyin']}.",
                room.version,
            )
        seat = TableSeat(
            room_id=room_id,
            seat_no=seat_no,
            member_id=member.id,
            stack=buyin,
            participation_state="WAITING_FOR_BLIND",
            pending_leave=False,
            sit_out_next=False,
        )
        tx.db.add(seat)
        _ledger(tx, member.id, "BUY_IN", buyin)
        await tx.db.flush()
        v = tx.bump()
        tx.emit("player.joined", {"seat_no": seat_no, "member_id": str(member.id), "stack": buyin})
        return {
            "seat_no": seat_no,
            "stack": buyin,
            "participation_state": "WAITING_FOR_BLIND",
            "room_version": v,
        }


async def set_sit_out(room_id: uuid.UUID, guest_id: uuid.UUID, sit_out: bool) -> dict:
    async with room_tx(room_id) as tx:
        member = await member_of(tx.db, room_id, guest_id)
        seat = await seat_of(tx.db, room_id, member.id)
        if seat is None:
            raise ServiceError("INVALID_ACTION", "You are not seated.", tx.room.version)
        hand = await live_hand(tx.db, room_id)
        in_hand = (
            hand is not None
            and seat.seat_no in seat_members(hand)
            and seat_members(hand)[seat.seat_no] == member.id
        )
        if sit_out:
            if in_hand:
                seat.sit_out_next = True  # effective after the current hand
            else:
                mark_sitting_out(seat)
        else:
            seat.sit_out_next = False
            if seat.participation_state == "SITTING_OUT":
                seat.participation_state = "WAITING_FOR_BLIND"  # blind re-entry policy
                seat.sitting_out_since = None
        v = tx.bump()
        tx.emit("player.sit_out", {"seat_no": seat.seat_no, "sit_out": sit_out})
        return {
            "seat_no": seat.seat_no,
            "participation_state": seat.participation_state,
            "sit_out_next": seat.sit_out_next,
            "room_version": v,
        }


def mark_sitting_out(seat: TableSeat) -> None:
    seat.participation_state = "SITTING_OUT"
    seat.sit_out_next = False
    if seat.sitting_out_since is None:
        seat.sitting_out_since = clock.now()


async def remove_from_table(tx: RoomTx, member_id: uuid.UUID) -> str:
    """Leave/kick: fold if still entitled to act, settle afterwards (SDD §3, §4).
    Returns 'COMPLETED' (cashed out now), 'PENDING' (after hand) or 'NOT_SEATED'."""
    seat = await seat_of(tx.db, tx.room.id, member_id)
    if seat is None:
        return "NOT_SEATED"
    hand = await live_hand(tx.db, tx.room.id)
    if hand is not None and seat_members(hand).get(seat.seat_no) == member_id:
        state = load_state(hand)
        p = state.players[seat.seat_no]
        seat.pending_leave = True
        if state.phase in BETTING_PHASES and p.can_act:
            out_of_turn = state.actor_seat != seat.seat_no
            new_state, events = force_fold(state, seat.seat_no)
            await _persist_hand(tx, hand, new_state, events, keep_deadline=out_of_turn)
        return "PENDING" if hand.ended_at is None else "COMPLETED"
    await _cash_out(tx, seat)
    return "COMPLETED"


async def leave(room_id: uuid.UUID, guest_id: uuid.UUID) -> dict:
    async with room_tx(room_id) as tx:
        member = await member_of(tx.db, room_id, guest_id, allow_banned=True)
        status = await remove_from_table(tx, member.id)
        if status == "NOT_SEATED":
            raise ServiceError("INVALID_ACTION", "You are not seated.", tx.room.version)
        v = tx.bump()
        return {"status": status, "room_version": v}


# ---------------------------------------------------------------------------
# hand lifecycle
# ---------------------------------------------------------------------------
def _deadline_for(tx: RoomTx, state: HandState):
    if (
        state.phase in BETTING_PHASES
        and state.actor_seat is not None
        and tx.room.operational_status == "ACTIVE"
    ):
        return clock.now() + timedelta(seconds=get_settings().action_timeout_seconds)
    return None


async def _persist_hand(
    tx: RoomTx,
    hand: Hand,
    state: HandState,
    events: list[dict[str, Any]],
    *,
    actor_member_id: uuid.UUID | None = None,
    action_id: uuid.UUID | None = None,
    keep_deadline: bool = False,
) -> int:
    """Write snapshot + players + materialized stacks + append-only events, bump version."""
    cipher = get_cipher()
    version = tx.bump()
    hand.hand_snapshot_encrypted = cipher.encrypt_json(state.to_dict(), aad=hand.id.bytes)
    hand.phase = state.phase.value
    if not (keep_deadline and hand.actor_seat == state.actor_seat):
        hand.deadline_at = _deadline_for(tx, state)
    hand.actor_seat = state.actor_seat
    hand.room_version = version

    members = seat_members(hand)
    rows = {
        hp.seat_no: hp
        for hp in (await tx.db.scalars(select(HandPlayer).where(HandPlayer.hand_id == hand.id)))
    }
    for s, p in state.players.items():
        hp = rows[s]
        hp.street_contribution = p.street_contribution
        hp.total_contribution = p.total_contribution
        hp.folded, hp.all_in, hp.show_status = p.folded, p.all_in, p.show_status.value
        seat = await tx.db.get(TableSeat, (tx.room.id, s))
        if seat is not None and seat.member_id == members[s]:
            seat.stack = p.stack

    for e in events:
        is_action = e["type"] == "action.result" and action_id is not None
        priv = None
        if e["private"] is not None:
            priv = cipher.encrypt_json(e["private"], aad=hand.id.bytes + str(e["seq"]).encode())
        tx.db.add(
            HandEvent(
                id=uuid.uuid4(),
                hand_id=hand.id,
                seq=e["seq"],
                action_id=action_id if is_action else None,
                actor_id=actor_member_id if is_action else None,
                event_type=e["type"],
                public_payload=e["public"],
                private_payload_ciphertext=priv,
                private_to_seat=e["private_to"],
                version=version,
            )
        )
        if e["private_to"] is not None:
            tx.emit(
                e["type"],
                e["private"] | e["public"],
                hand_id=str(hand.id),
                private_to_member=str(members[e["private_to"]]),
            )
        else:
            # engine "action.result" is broadcast as "game.action"; "action.result" on the
            # socket is reserved for the direct reply to the command sender.
            wire = "game.action" if e["type"] == "action.result" else e["type"]
            tx.emit(wire, e["public"], hand_id=str(hand.id), seq=e["seq"])

    if state.phase == Phase.HAND_COMPLETE:
        await _finalize(tx, hand)
    elif hand.deadline_at is not None:
        room_id, hand_id, deadline = tx.room.id, hand.id, hand.deadline_at
        tx.after_commit.append(lambda: timers.schedule(room_id, hand_id, deadline))
    return version


async def _finalize(tx: RoomTx, hand: Hand) -> None:
    metrics.inc("hands_completed")
    hand.ended_at = clock.now()
    hand.deadline_at = None
    hand.actor_seat = None
    members = seat_members(hand)
    for s, member_id in members.items():
        seat = await tx.db.get(TableSeat, (tx.room.id, s))
        if seat is None or seat.member_id != member_id:
            continue
        if seat.pending_leave:
            await _cash_out(tx, seat)
        elif seat.sit_out_next:
            mark_sitting_out(seat)
    room_id = tx.room.id
    tx.after_commit.append(lambda: timers.cancel(room_id))
    if tx.room.auto_deal and tx.room.status != "CLOSED":
        at = clock.now() + timedelta(seconds=get_settings().auto_deal_delay_seconds)
        tx.room.next_hand_at = at
        tx.after_commit.append(lambda: timers.schedule_deal(room_id, at))


async def start_next_hand(
    room_id: uuid.UUID,
    guest_id: uuid.UUID,
    *,
    expected_version: int | None = None,
    idempotency_key: str | None = None,
) -> dict:
    async with room_tx(room_id) as tx:
        room = tx.room
        member = await member_of(tx.db, room_id, guest_id)
        require_host(room, member)
        require_open(room)
        if idempotency_key:
            prior = await tx.db.scalar(
                select(Hand).where(Hand.room_id == room_id, Hand.idempotency_key == idempotency_key)
            )
            if prior is not None:
                return {"hand_id": str(prior.id), "room_version": room.version, "replayed": True}
        require_version(room, expected_version)
        return await _start_hand(tx, idempotency_key)


async def auto_start_hand(room_id: uuid.UUID) -> bool:
    """Auto-deal wake-up (timer or sweeper). Re-validated under the room lock; a
    table without two eligible players just waits (next_hand_at stays armed)."""
    try:
        async with room_tx(room_id) as tx:
            room = tx.room
            if (
                not room.auto_deal
                or room.next_hand_at is None
                or clock.now() < room.next_hand_at
                or room.status == "CLOSED"
                or room.operational_status != "ACTIVE"
                or lifecycle.draining
                or await live_hand(tx.db, room_id) is not None
            ):
                return False
            seats = (
                await tx.db.scalars(select(TableSeat).where(TableSeat.room_id == room_id))
            ).all()
            if len([s for s in seats if _eligible(s)]) < 2:
                return False
            await _start_hand(tx, None)
            return True
    except ServiceError:
        return False


def _eligible(s: TableSeat) -> bool:
    return (
        s.stack > 0
        and not s.pending_leave
        and not s.sit_out_next
        and s.participation_state in ("ACTIVE", "WAITING_FOR_BLIND")
    )


async def set_auto_deal(room_id: uuid.UUID, guest_id: uuid.UUID, enabled: bool) -> dict:
    async with room_tx(room_id) as tx:
        member = await member_of(tx.db, room_id, guest_id)
        require_host(tx.room, member)
        room = tx.room
        room.auto_deal = enabled
        at = None
        if enabled:
            if await live_hand(tx.db, room_id) is None:
                at = clock.now() + timedelta(seconds=get_settings().auto_deal_delay_seconds)
        room.next_hand_at = at
        if at is not None:
            tx.after_commit.append(lambda: timers.schedule_deal(room_id, at))
        v = tx.bump()
        tx.emit("room.auto_deal", {"enabled": enabled})
        return {"auto_deal": enabled, "room_version": v}


async def _start_hand(tx: RoomTx, idempotency_key: str | None) -> dict:
    room, room_id = tx.room, tx.room.id
    if lifecycle.draining:
        raise ServiceError("ROOM_PAUSED", "Server is restarting; try again shortly.", room.version)
    if room.operational_status != "ACTIVE":
        raise ServiceError("ROOM_PAUSED", "Room is paused; host must resume.", room.version)
    if await live_hand(tx.db, room_id) is not None:
        raise ServiceError("HAND_ALREADY_RUNNING", "A hand is already running.", room.version)

    # between-hands boundary: pending config, then approved top-ups
    if room.pending_config_json:
        room.config_json = {**room.config_json, **room.pending_config_json}
        room.pending_config_json = None
    await apply_approved_topups(tx)
    await tx.db.flush()

    seats = (await tx.db.scalars(select(TableSeat).where(TableSeat.room_id == room_id))).all()
    eligible = [s for s in seats if _eligible(s)]
    active = [s.seat_no for s in eligible if s.participation_state == "ACTIVE"]
    waiting = [s.seat_no for s in eligible if s.participation_state == "WAITING_FOR_BLIND"]
    try:
        pos = next_hand_positions(active, waiting, room.bb_seat)
    except EngineError:
        raise ServiceError(
            "INVALID_ACTION", "At least two eligible seated players are required.", room.version
        ) from None
    by_no = {s.seat_no: s for s in seats}
    cfg = _config(room)
    hand_cfg = HandConfig(small_blind=cfg["sb"], big_blind=cfg["bb"])
    state, events = start_hand(hand_cfg, {n: by_no[n].stack for n in pos.participants}, pos.button)
    assert state.bb_seat == pos.big_blind

    ordinal = (
        await tx.db.scalar(
            select(func.coalesce(func.max(Hand.ordinal), 0)).where(Hand.room_id == room_id)
        )
    ) + 1
    hand_id = uuid.uuid4()
    snapshot_cfg = {
        "sb": hand_cfg.small_blind,
        "bb": hand_cfg.big_blind,
        "rules_version": hand_cfg.rules_version,
        "button_seat": pos.button,
        "seat_order": list(pos.participants),
        "min_buyin": cfg["min_buyin"],
        "max_buyin": cfg["max_buyin"],
        "seat_members": {str(n): str(by_no[n].member_id) for n in pos.participants},
    }
    hand = Hand(
        id=hand_id,
        room_id=room_id,
        ordinal=ordinal,
        phase=state.phase.value,
        button_seat=pos.button,
        config_snapshot=snapshot_cfg,
        room_version=room.version,
        hand_snapshot_encrypted=b"\x00",
        idempotency_key=idempotency_key,
    )
    tx.db.add(hand)
    await tx.db.flush()
    cipher = get_cipher()
    for n in pos.participants:
        p = state.players[n]
        tx.db.add(
            HandPlayer(
                hand_id=hand_id,
                seat_no=n,
                member_id=by_no[n].member_id,
                hole_cards_ciphertext=cipher.encrypt_json(
                    p.hole_cards, aad=hand_id.bytes + bytes([n])
                ),
                street_contribution=0,
                total_contribution=0,
                folded=False,
                all_in=False,
                show_status="HIDDEN",
            )
        )
        by_no[n].participation_state = "ACTIVE"
    await tx.db.flush()
    room.button_seat, room.bb_seat = pos.button, pos.big_blind
    room.next_hand_at = None
    tx.emit("hand.started_meta", {"hand_id": str(hand_id), "ordinal": ordinal})
    version = await _persist_hand(tx, hand, state, events)
    return {
        "hand_id": str(hand_id),
        "ordinal": ordinal,
        "room_version": version,
        "replayed": False,
    }


async def player_action(
    room_id: uuid.UUID,
    guest_id: uuid.UUID,
    *,
    action_id: uuid.UUID,
    hand_id: uuid.UUID,
    expected_version: int,
    action: str,
    raise_to: int | None = None,
) -> dict:
    """Appendix A: authoritative, idempotent, serialized player action."""
    async with room_tx(room_id) as tx:
        room = tx.room
        member = await member_of(tx.db, room_id, guest_id)
        prior = await tx.db.get(ActionResult, (room_id, member.id, action_id))
        if prior is not None:
            return prior.result | {"replayed": True}
        require_version(room, expected_version)
        if room.operational_status != "ACTIVE":
            raise ServiceError("ROOM_PAUSED", "Room is paused.", room.version)
        hand = await live_hand(tx.db, room_id)
        if hand is None or hand.id != hand_id:
            raise ServiceError("INVALID_ACTION", "That hand is not active.", room.version)
        seat_no = next((s for s, m in seat_members(hand).items() if m == member.id), None)
        if seat_no is None:
            raise ServiceError("INVALID_ACTION", "You are not in this hand.", room.version)
        if hand.actor_seat != seat_no:
            raise ServiceError(
                "NOT_YOUR_TURN", "Only the current actor may submit a poker action.", room.version
            )
        if hand.deadline_at is not None and clock.now() > hand.deadline_at:
            raise ServiceError("DEADLINE_EXPIRED", "Action deadline passed.", room.version)
        try:
            act = ActionType(action)
        except ValueError:
            raise ServiceError("INVALID_ACTION", "Unknown action.", room.version) from None
        try:
            new_state, events = apply_action(load_state(hand), seat_no, act, raise_to)
        except EngineError as e:
            raise ServiceError(e.code, e.message, room.version) from None
        version = await _persist_hand(
            tx, hand, new_state, events, actor_member_id=member.id, action_id=action_id
        )
        result = {"accepted": True, "room_version": version, "hand_id": str(hand.id)}
        tx.db.add(
            ActionResult(room_id=room_id, actor_id=member.id, action_id=action_id, result=result)
        )
        return result


async def process_timeout(
    room_id: uuid.UUID, hand_id: uuid.UUID | None = None, expected_version: int | None = None
) -> bool:
    """Timer/sweeper wake-up: reload and validate (live hand, deadline passed), then
    fold the actor and sit them out from the next hand. Idempotent: a stale wake-up
    is a no-op because the next actor's deadline lies in the future (SDD §9).

    Deliberately NOT keyed on room.version: unrelated room changes (someone sits
    down, host election, top-up requests) must not cancel a pending timeout.
    `expected_version` is accepted for backward compatibility and ignored."""
    del expected_version
    async with room_tx(room_id) as tx:
        room = tx.room
        if room.operational_status != "ACTIVE":
            return False
        hand = await live_hand(tx.db, room_id)
        if hand is None or (hand_id is not None and hand.id != hand_id):
            return False
        if hand.deadline_at is None or clock.now() < hand.deadline_at:
            return False
        state = load_state(hand)
        seat_no = state.actor_seat
        new_state, events = timeout_action(state)
        if seat_no is not None:
            seat = await tx.db.get(TableSeat, (room_id, seat_no))
            if seat is not None and seat.member_id == seat_members(hand).get(seat_no):
                seat.sit_out_next = True  # applied in _finalize -> SITTING_OUT
                tx.emit(
                    "player.sit_out",
                    {"seat_no": seat_no, "sit_out": True, "reason": "TIMEOUT"},
                )
        await _persist_hand(tx, hand, new_state, events)
        metrics.inc("timeouts")
        return True


async def overdue_rooms() -> list[uuid.UUID]:
    """Rooms whose live hand deadline has passed (sweeper safety net)."""
    from app.persistence.db import new_session

    async with new_session() as db:
        return list(
            (
                await db.scalars(
                    select(Hand.room_id)
                    .join(Room, Room.id == Hand.room_id)
                    .where(
                        Hand.ended_at.is_(None),
                        Hand.deadline_at.is_not(None),
                        Hand.deadline_at < clock.now() - timedelta(seconds=1),
                        Room.operational_status == "ACTIVE",
                    )
                )
            ).all()
        )


async def due_deal_rooms() -> list[uuid.UUID]:
    from app.persistence.db import new_session

    async with new_session() as db:
        return list(
            (
                await db.scalars(
                    select(Room.id).where(
                        Room.auto_deal.is_(True),
                        Room.next_hand_at.is_not(None),
                        Room.next_hand_at <= clock.now(),
                        Room.status != "CLOSED",
                        Room.operational_status == "ACTIVE",
                    )
                )
            ).all()
        )


# ---------------------------------------------------------------------------
# recovery (SDD §9)
# ---------------------------------------------------------------------------
async def pause_live_rooms_on_startup() -> list[uuid.UUID]:
    """After restart: freeze every room with an unfinished hand (PAUSED_RECOVERY),
    clear deadlines (never execute overdue actions), mark everyone disconnected."""
    from app.persistence.db import new_session

    async with new_session() as db, db.begin():
        ids = (await db.scalars(select(Hand.room_id).where(Hand.ended_at.is_(None)))).all()
        now = clock.now()
        members = (
            await db.scalars(select(RoomMember).where(RoomMember.disconnected_since.is_(None)))
        ).all()
        for m in members:
            m.disconnected_since = now
    paused = []
    for rid in ids:
        async with room_tx(rid) as tx:
            hand = await live_hand(tx.db, rid)
            if hand is None:
                continue
            tx.room.operational_status = "PAUSED_RECOVERY"
            hand.deadline_at = None
            tx.bump()
            tx.emit("room.paused", {"reason": "RECOVERY"})
            paused.append(rid)
    return paused


async def resume(room_id: uuid.UUID, guest_id: uuid.UUID) -> dict:
    async with room_tx(room_id) as tx:
        member = await member_of(tx.db, room_id, guest_id)
        require_host(tx.room, member)
        if tx.room.operational_status != "PAUSED_RECOVERY":
            raise ServiceError("INVALID_ACTION", "Room is not paused.", tx.room.version)
        tx.room.operational_status = "ACTIVE"
        hand = await live_hand(tx.db, room_id)
        deadline = None
        if hand is not None:
            state = load_state(hand)
            hand.deadline_at = deadline = _deadline_for(tx, state)  # fresh 30 s from resume
        v = tx.bump()
        if hand is not None:
            hand.room_version = v
            if deadline is not None:
                rid, hid = room_id, hand.id
                tx.after_commit.append(lambda: timers.schedule(rid, hid, deadline))
        tx.emit("room.resumed", {"deadline_at": deadline.isoformat() if deadline else None})
        return {
            "room_version": v,
            "hand_id": str(hand.id) if hand else None,
            "deadline_at": deadline.isoformat() if deadline else None,
        }
