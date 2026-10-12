"""Durable multiplayer tests (SDD §13.2): simulated full hands, concurrency,
top-ups, leave, bans, host election, recovery, closure."""

import asyncio
import random
import uuid
from datetime import timedelta

import pytest
from sqlalchemy import func, select

from app.persistence.db import new_session
from app.persistence.models import ChipLedger, Hand, HandEvent, Room, TableSeat
from app.services import clock, rooms, table
from app.services.errors import ServiceError
from tests.integration.conftest import TEST_DB
from tests.integration.factory import (
    PASSWORD,
    act,
    actor_guest,
    chip_totals,
    make_guest,
    make_table,
    play_hand_randomly,
    view_for,
)

pytestmark = [
    pytest.mark.skipif(not TEST_DB, reason="POKER_TEST_DATABASE_URL not set"),
    pytest.mark.usefixtures("app"),
]


async def start(room_id, host, **kw):
    v = await view_for(room_id, host)
    return await table.start_next_hand(room_id, host, expected_version=v["room_version"], **kw)


# ---------------------------------------------------------------------------
# full hands + conservation
# ---------------------------------------------------------------------------
async def test_simulated_hands_conserve_chips():
    room_id, guests, _ = await make_table(4, seats=[1, 3, 6, 8])
    rng = random.Random(7)
    by_member = {(await view_for(room_id, g))["me"]["member_id"]: g for g in guests}
    for i in range(25):
        await start(room_id, guests[0])
        net, on_table = await chip_totals(room_id)
        assert net == on_table
        await play_hand_randomly(room_id, guests, rng)
        net, on_table = await chip_totals(room_id)
        assert net == on_table, f"hand {i}"
        # re-buy busted players via top-up so the game continues
        v = await view_for(room_id, guests[0])
        for s in v["seats"]:
            if s["stack"] == 0:
                g = by_member[s["member_id"]]
                r = await rooms.request_topup(room_id, g, 500)
                await rooms.decide_topup(room_id, guests[0], uuid.UUID(r["request_id"]), True)
        if sum(1 for s in (await view_for(room_id, guests[0]))["seats"] if s["stack"] > 0) < 2:
            break
    async with new_session() as db:
        assert (
            await db.scalar(select(func.count()).select_from(Hand).where(Hand.room_id == room_id))
            >= 10
        )
        assert (
            await db.scalar(select(func.min(TableSeat.stack)).where(TableSeat.room_id == room_id))
            >= 0
        )


async def test_private_cards_only_for_owner_and_not_spectators():
    room_id, guests, invite = await make_table(3)
    spectator = await make_guest("watcher")
    await rooms.join_room(
        room_id, spectator, invite_token=invite["invite_token"], password=PASSWORD, client_ip="spec"
    )
    await start(room_id, guests[0])
    views = [await view_for(room_id, g) for g in guests]
    spec = await view_for(room_id, spectator)
    all_cards = {c for v in views for c in v["hand"]["your_cards"]}
    assert len(all_cards) == 6
    assert "your_cards" not in spec["hand"]
    blob = str(spec)
    assert not any(f"'{c}'" in blob for c in all_cards)
    for v in views:
        others = all_cards - set(v["hand"]["your_cards"])
        assert not any(f"'{c}'" in str(v) for c in others)
    # snapshot and hole cards are encrypted at rest
    async with new_session() as db:
        h = await db.scalar(select(Hand).where(Hand.room_id == room_id))
        assert all(f'"{c}"'.encode() not in h.hand_snapshot_encrypted for c in all_cards)
        assert b"hole_cards" not in h.hand_snapshot_encrypted


async def test_start_hand_rules():
    room_id, guests, _ = await make_table(2)
    with pytest.raises(ServiceError) as e:
        await start(room_id, guests[1])
    assert e.value.code == "NOT_HOST"
    with pytest.raises(ServiceError) as e:
        await table.start_next_hand(room_id, guests[0], expected_version=0)
    assert e.value.code == "STALE_VERSION"
    r1 = await start(room_id, guests[0], idempotency_key="k1")
    r2 = await table.start_next_hand(room_id, guests[0], idempotency_key="k1")
    assert r1["hand_id"] == r2["hand_id"] and r2["replayed"]
    with pytest.raises(ServiceError) as e:
        await table.start_next_hand(room_id, guests[0], idempotency_key="k2")
    assert e.value.code == "HAND_ALREADY_RUNNING"


async def test_needs_two_eligible_players():
    room_id, guests, _ = await make_table(2)
    await table.set_sit_out(room_id, guests[1], True)
    with pytest.raises(ServiceError) as e:
        await start(room_id, guests[0])
    assert e.value.code == "INVALID_ACTION"


# ---------------------------------------------------------------------------
# concurrency (SDD §13.2)
# ---------------------------------------------------------------------------
async def test_duplicate_action_id_is_idempotent_under_concurrency():
    room_id, guests, _ = await make_table(3)
    await start(room_id, guests[0])
    g, v = await actor_guest(room_id, guests)
    aid = uuid.uuid4()
    results = await asyncio.gather(*[act(room_id, g, v, "CALL", action_id=aid) for _ in range(5)])
    assert len({r["room_version"] for r in results}) == 1
    assert sum(1 for r in results if not r.get("replayed")) == 1
    async with new_session() as db:
        n = await db.scalar(
            select(func.count()).select_from(HandEvent).where(HandEvent.action_id == aid)
        )
        assert n == 1


async def test_stale_version_race_only_one_wins():
    room_id, guests, _ = await make_table(3)
    await start(room_id, guests[0])
    g, v = await actor_guest(room_id, guests)
    res = await asyncio.gather(
        act(room_id, g, v, "CALL"), act(room_id, g, v, "FOLD"), return_exceptions=True
    )
    ok = [r for r in res if isinstance(r, dict)]
    errs = [r for r in res if isinstance(r, ServiceError)]
    assert len(ok) == 1 and len(errs) == 1 and errs[0].code == "STALE_VERSION"


async def test_action_vs_timeout_race_exactly_one_applies():
    room_id, guests, _ = await make_table(3)
    await start(room_id, guests[0])
    g, v = await actor_guest(room_id, guests)
    async with new_session() as db:
        hand = await db.scalar(select(Hand).where(Hand.room_id == room_id, Hand.ended_at.is_(None)))
        version, hand_id = (await db.get(Room, room_id)).version, hand.id
    clock.advance(timedelta(seconds=31))
    res = await asyncio.gather(
        table.process_timeout(room_id, hand_id, version),
        act(room_id, g, v, "CALL"),
        return_exceptions=True,
    )
    applied = (res[0] is True) + isinstance(res[1], dict)
    assert applied == 1
    if res[0] is True:
        assert isinstance(res[1], ServiceError)
        assert res[1].code in ("STALE_VERSION", "DEADLINE_EXPIRED")


async def test_post_deadline_action_rejected_and_timeout_folds():
    room_id, guests, _ = await make_table(3)
    await start(room_id, guests[0])
    g, v = await actor_guest(room_id, guests)
    clock.advance(timedelta(seconds=31))
    with pytest.raises(ServiceError) as e:
        await act(room_id, g, v, "CALL")
    assert e.value.code == "DEADLINE_EXPIRED"
    assert await table.process_timeout(room_id, uuid.UUID(v["hand"]["hand_id"]), v["room_version"])
    # stale wake-up is a no-op
    assert not await table.process_timeout(
        room_id, uuid.UUID(v["hand"]["hand_id"]), v["room_version"]
    )
    v2 = await view_for(room_id, g)
    me = next(s for s in v2["hand"]["seats"] if s["seat_no"] == v2["me"]["seat_no"])
    assert me["folded"]  # facing the BB -> timeout folds


async def test_concurrent_start_hand_only_one_hand():
    room_id, guests, _ = await make_table(3)
    v = await view_for(room_id, guests[0])
    res = await asyncio.gather(
        *[
            table.start_next_hand(
                room_id, guests[0], expected_version=v["room_version"], idempotency_key=f"key-{i}"
            )
            for i in range(4)
        ],
        return_exceptions=True,
    )
    assert sum(isinstance(r, dict) for r in res) == 1
    async with new_session() as db:
        assert (
            await db.scalar(
                select(func.count())
                .select_from(Hand)
                .where(Hand.room_id == room_id, Hand.ended_at.is_(None))
            )
            == 1
        )


# ---------------------------------------------------------------------------
# top-ups, leave, sit-out
# ---------------------------------------------------------------------------
async def test_topup_during_live_hand_applies_only_at_next_boundary():
    room_id, guests, _ = await make_table(2, buyin=1000, max_buyin=1500)
    await start(room_id, guests[0])
    with pytest.raises(ServiceError) as e:
        await rooms.request_topup(room_id, guests[1], 600)
    assert e.value.code == "TOPUP_LIMIT_EXCEEDED"
    r = await rooms.request_topup(room_id, guests[1], 300)
    await rooms.decide_topup(room_id, guests[0], uuid.UUID(r["request_id"]), True)
    before = next(s for s in (await view_for(room_id, guests[1]))["seats"] if s["seat_no"] == 2)
    assert before["stack"] < 1000  # blinds posted, top-up NOT applied mid-hand
    # finish the hand: everybody folds to end quickly
    while (await view_for(room_id, guests[0]))["hand"] is not None:
        g, v = await actor_guest(room_id, guests)
        await act(room_id, g, v, "FOLD")
    stack_after_hand = next(
        s for s in (await view_for(room_id, guests[1]))["seats"] if s["seat_no"] == 2
    )["stack"]
    await start(room_id, guests[0])
    async with new_session() as db:
        topups = await db.scalar(
            select(func.count())
            .select_from(ChipLedger)
            .where(ChipLedger.room_id == room_id, ChipLedger.type == "TOP_UP")
        )
    assert topups == (1 if stack_after_hand + 300 <= 1500 else 0)
    net, on_table = await chip_totals(room_id)
    assert net == on_table


async def test_leave_mid_hand_folds_and_cashes_out_after_settlement():
    room_id, guests, _ = await make_table(3)
    await start(room_id, guests[0])
    g, v = await actor_guest(room_id, guests)
    leaver = next(x for x in guests if x != g)  # out of turn
    r = await table.leave(room_id, leaver)
    assert r["status"] in ("PENDING", "COMPLETED")
    while (await view_for(room_id, guests[0]))["hand"] is not None:
        g, v = await actor_guest(room_id, [x for x in guests if x != leaver])
        await act(room_id, g, v, "CHECK" if v["hand"]["legal_actions"]["can_check"] else "CALL")
    assert (await view_for(room_id, leaver))["me"]["seat_no"] is None
    net, on_table = await chip_totals(room_id)
    assert net == on_table


async def test_leave_while_all_in_stays_until_settlement():
    room_id, guests, _ = await make_table(3)
    await start(room_id, guests[0])
    g, v = await actor_guest(room_id, guests)
    await act(room_id, g, v, "ALL_IN")
    r = await table.leave(room_id, g)
    assert r["status"] == "PENDING"
    v = await view_for(room_id, g)
    assert v["me"]["seat_no"] is not None and v["hand"] is not None
    while (await view_for(room_id, guests[0]))["hand"] is not None:
        g2, v2 = await actor_guest(room_id, guests)
        await act(room_id, g2, v2, "FOLD")
    assert (await view_for(room_id, g))["me"]["seat_no"] is None


async def test_sit_out_and_wait_for_bb_reentry():
    room_id, guests, _ = await make_table(3)
    await start(room_id, guests[0])
    await table.set_sit_out(room_id, guests[2], True)
    while (await view_for(room_id, guests[0]))["hand"] is not None:
        g, v = await actor_guest(room_id, guests)
        await act(room_id, g, v, "FOLD")
    seat = next(s for s in (await view_for(room_id, guests[0]))["seats"] if s["seat_no"] == 3)
    assert seat["participation_state"] == "SITTING_OUT"
    await start(room_id, guests[0])
    assert 3 not in [s["seat_no"] for s in (await view_for(room_id, guests[0]))["hand"]["seats"]]
    await table.set_sit_out(room_id, guests[2], False)
    seat = next(s for s in (await view_for(room_id, guests[0]))["seats"] if s["seat_no"] == 3)
    assert seat["participation_state"] == "WAITING_FOR_BLIND"


# ---------------------------------------------------------------------------
# host, bans, recovery, closure
# ---------------------------------------------------------------------------
async def test_ban_removes_and_blocks_rejoin_unban_restores():
    room_id, guests, invite = await make_table(3)
    target_member = uuid.UUID((await view_for(room_id, guests[2]))["me"]["member_id"])
    await rooms.kick(room_id, guests[0], target_member, ban=True)
    assert (await view_for(room_id, guests[0]))["seats"].__len__() == 2
    with pytest.raises(ServiceError) as e:
        await table.claim_seat(room_id, guests[2], 5, 500)
    assert e.value.code == "ROOM_BANNED"
    with pytest.raises(ServiceError) as e:
        await rooms.join_room(
            room_id,
            guests[2],
            invite_token=invite["invite_token"],
            password=PASSWORD,
            client_ip="x",
        )
    assert e.value.code == "ROOM_BANNED"
    await rooms.unban(room_id, guests[0], target_member)
    await rooms.join_room(
        room_id, guests[2], invite_token=invite["invite_token"], password=PASSWORD, client_ip="x"
    )
    await table.claim_seat(room_id, guests[2], 5, 500)


async def test_wrong_invite_and_password_rate_limited():
    room_id, guests, invite = await make_table(2)
    g = await make_guest("guesser")
    with pytest.raises(ServiceError) as e:
        await rooms.join_room(room_id, g, invite_token="nope", password=PASSWORD)
    assert e.value.code == "UNAUTHORIZED"
    codes = []
    for _ in range(6):
        try:
            await rooms.join_room(room_id, g, invite_token=invite["invite_token"], password="bad")
        except ServiceError as err:
            codes.append(err.code)
    assert "INVALID_PASSWORD" in codes and codes[-1] == "RATE_LIMITED"


async def test_host_transfer_and_election_after_grace():
    room_id, guests, _ = await make_table(3)
    members = [uuid.UUID((await view_for(room_id, g))["me"]["member_id"]) for g in guests]
    connected = set(members)
    for m in members:
        await rooms.on_connect(room_id, m, connected)
    # host disconnects; before 60 s nothing changes
    connected.discard(members[0])
    await rooms.on_disconnect(room_id, members[0], connected)
    clock.advance(timedelta(seconds=30))
    await rooms.sweep_room(room_id, connected)
    assert (await view_for(room_id, guests[0]))["host_member_id"] == str(members[0])
    clock.advance(timedelta(seconds=31))
    await rooms.sweep_room(room_id, connected)
    v = await view_for(room_id, guests[0])
    assert v["host_member_id"] == str(members[1])  # earliest-joined connected member
    # former host reconnects: does not reclaim authority
    connected.add(members[0])
    await rooms.on_connect(room_id, members[0], connected)
    await rooms.sweep_room(room_id, connected)
    assert (await view_for(room_id, guests[0]))["host_member_id"] == str(members[1])
    with pytest.raises(ServiceError):
        await start(room_id, guests[0])
    await rooms.transfer_host(room_id, guests[1], members[2])
    assert (await view_for(room_id, guests[0]))["host_member_id"] == str(members[2])


async def test_recovery_pauses_and_host_resume_sets_fresh_deadline():
    room_id, guests, _ = await make_table(3)
    await start(room_id, guests[0])
    g, v = await actor_guest(room_id, guests)
    paused = await table.pause_live_rooms_on_startup()
    assert room_id in paused
    v2 = await view_for(room_id, g)
    assert v2["operational_status"] == "PAUSED_RECOVERY" and v2["hand"]["deadline_at"] is None
    with pytest.raises(ServiceError) as e:
        await act(room_id, g, v2, "CALL")
    assert e.value.code == "ROOM_PAUSED"
    clock.advance(timedelta(minutes=10))
    assert not await table.process_timeout(
        room_id, uuid.UUID(v2["hand"]["hand_id"]), v2["room_version"]
    )
    with pytest.raises(ServiceError):
        await table.resume(room_id, guests[1])
    r = await table.resume(room_id, guests[0])
    v3 = await view_for(room_id, g)
    assert v3["operational_status"] == "ACTIVE" and v3["hand"]["deadline_at"] == r["deadline_at"]
    # same actor, same cards: state restored exactly
    assert v3["hand"]["your_cards"] == v["hand"]["your_cards"]
    assert v3["hand"]["actor_seat"] == v["hand"]["actor_seat"]
    await act(room_id, g, v3, "CALL")


async def test_empty_room_closes_after_24h_and_keeps_archives():
    room_id, guests, _ = await make_table(2)
    await start(room_id, guests[0])
    while (await view_for(room_id, guests[0]))["hand"] is not None:
        g, v = await actor_guest(room_id, guests)
        await act(room_id, g, v, "FOLD")
    m = uuid.UUID((await view_for(room_id, guests[0]))["me"]["member_id"])
    await rooms.on_connect(room_id, m, {m})
    await rooms.on_disconnect(room_id, m, set())
    assert (await view_for(room_id, guests[0]))["status"] == "EMPTY_PENDING_CLOSE"
    clock.advance(timedelta(hours=23))
    await rooms.sweep_room(room_id, set())
    assert (await view_for(room_id, guests[0]))["status"] == "EMPTY_PENDING_CLOSE"
    clock.advance(timedelta(hours=2))
    await rooms.sweep_room(room_id, set())
    v = await view_for(room_id, guests[0])
    assert v["status"] == "CLOSED" and v["seats"] == []
    net, on_table = await chip_totals(room_id)
    assert net == on_table == 0
    async with new_session() as db:
        assert (
            await db.scalar(select(func.count()).select_from(Hand).where(Hand.room_id == room_id))
            == 1
        )


async def test_config_change_applies_at_next_hand():
    room_id, guests, _ = await make_table(2)
    await start(room_id, guests[0])
    r = await rooms.update_config(room_id, guests[0], {"sb": 10, "bb": 20})
    assert not r["applied_now"]
    v = await view_for(room_id, guests[0])
    assert v["config"]["bb"] == 10 and v["pending_config"]["bb"] == 20
    with pytest.raises(ServiceError):
        await rooms.update_config(room_id, guests[0], {"sb": 30})  # sb >= bb
    while (await view_for(room_id, guests[0]))["hand"] is not None:
        g, v = await actor_guest(room_id, guests)
        await act(room_id, g, v, "FOLD")
    await start(room_id, guests[0])
    v = await view_for(room_id, guests[0])
    assert v["config"]["bb"] == 20 and v["pending_config"] is None
    assert v["hand"]["current_bet"] == 20


async def test_new_player_is_dealt_into_the_next_hand():
    """A-01: players may enter at any time (no waiting for the big blind)."""
    room_id, guests, invite = await make_table(3)
    await start(room_id, guests[0])
    late = await make_guest("late")
    await rooms.join_room(
        room_id, late, invite_token=invite["invite_token"], password=PASSWORD, client_ip="late"
    )
    await table.claim_seat(room_id, late, 7, 500)
    hand_seats = [s["seat_no"] for s in (await view_for(room_id, guests[0]))["hand"]["seats"]]
    assert 7 not in hand_seats  # cannot join a hand already in progress
    while (await view_for(room_id, guests[0]))["hand"] is not None:
        g, v = await actor_guest(room_id, guests)
        await act(room_id, g, v, "FOLD")
    await start(room_id, guests[0])
    v = await view_for(room_id, late)
    assert 7 in [s["seat_no"] for s in v["hand"]["seats"]] and len(v["hand"]["your_cards"]) == 2
