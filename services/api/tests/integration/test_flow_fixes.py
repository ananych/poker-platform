"""Playtest fixes (2026-10): timeouts never stall, timeout = fold + sit out,
auto-deal between hands, idle sit-out stand-up, own cards in result, P/L."""

import uuid
from datetime import timedelta

import pytest

from app.realtime import jobs
from app.services import clock, rooms, table
from app.services.errors import ServiceError
from tests.integration.conftest import TEST_DB
from tests.integration.factory import PASSWORD, act, actor_guest, make_guest, make_table, view_for

pytestmark = [
    pytest.mark.skipif(not TEST_DB, reason="POKER_TEST_DATABASE_URL not set"),
    pytest.mark.usefixtures("app"),
]


async def start(room_id, host):
    v = await view_for(room_id, host)
    return await table.start_next_hand(room_id, host, expected_version=v["room_version"])


async def fold_out(room_id, guests):
    while (await view_for(room_id, guests[0]))["hand"] is not None:
        g, v = await actor_guest(room_id, guests)
        await act(room_id, g, v, "FOLD")


async def test_unrelated_room_change_does_not_cancel_timeout():
    room_id, guests, invite = await make_table(3)
    await start(room_id, guests[0])
    g, v = await actor_guest(room_id, guests)
    hand_id = uuid.UUID(v["hand"]["hand_id"])
    # someone joins and sits down mid-turn -> room version moves on
    newbie = await make_guest("late")
    await rooms.join_room(
        room_id, newbie, invite_token=invite["invite_token"], password=PASSWORD, client_ip="x"
    )
    await table.claim_seat(room_id, newbie, 7, 500)
    assert (await view_for(room_id, g))["room_version"] > v["room_version"]
    clock.advance(timedelta(seconds=31))
    assert await table.process_timeout(room_id, hand_id, v["room_version"])  # stale version ok
    v2 = await view_for(room_id, g)
    seat = next(s for s in v2["seats"] if s["seat_no"] == v2["me"]["seat_no"])
    me = next(s for s in v2["hand"]["seats"] if s["seat_no"] == v2["me"]["seat_no"])
    assert me["folded"] and seat["sit_out_next"]


async def test_timeout_folds_even_when_check_is_free_and_sits_out():
    room_id, guests, _ = await make_table(2)
    await start(room_id, guests[0])
    g, v = await actor_guest(room_id, guests)  # heads-up: button/SB acts first
    await act(room_id, g, v, "CALL")
    bb, vbb = await actor_guest(room_id, guests)
    assert vbb["hand"]["legal_actions"]["can_check"]
    clock.advance(timedelta(seconds=31))
    assert await table.process_timeout(room_id)
    v2 = await view_for(room_id, bb)
    assert v2["hand"] is None  # BB folded -> hand over
    seat = next(s for s in v2["seats"] if s["seat_no"] == v2["me"]["seat_no"])
    assert seat["participation_state"] == "SITTING_OUT"
    # coming back clears it
    await table.set_sit_out(room_id, bb, False)
    seat = next(
        s for s in (await view_for(room_id, bb))["seats"] if s["seat_no"] == v2["me"]["seat_no"]
    )
    assert seat["participation_state"] == "WAITING_FOR_BLIND"


async def test_sweeper_recovers_overdue_deadline_without_timer():
    room_id, guests, _ = await make_table(3)
    await start(room_id, guests[0])
    v = await view_for(room_id, guests[0])
    clock.advance(timedelta(seconds=40))
    assert room_id in await table.overdue_rooms()
    await jobs.sweep_once()
    v2 = await view_for(room_id, guests[0])
    assert v2["hand"]["actor_seat"] != v["hand"]["actor_seat"] or v2["hand"] is None


async def test_auto_deal_after_hand_and_host_can_pause():
    room_id, guests, _ = await make_table(3)
    await start(room_id, guests[0])
    await fold_out(room_id, guests)
    v = await view_for(room_id, guests[1])
    assert v["auto_deal"] and v["next_hand_at"] is not None
    assert not await table.auto_start_hand(room_id)  # too early
    clock.advance(timedelta(seconds=6))
    assert room_id in await table.due_deal_rooms()
    await jobs.sweep_once()  # host absent: deals anyway
    v = await view_for(room_id, guests[1])
    assert v["hand"] is not None and v["hand"]["ordinal"] == 2 and v["next_hand_at"] is None
    await fold_out(room_id, guests)
    # non-host cannot pause; host pauses -> nothing armed
    with pytest.raises(ServiceError) as e:
        await table.set_auto_deal(room_id, guests[1], False)
    assert e.value.code == "NOT_HOST"
    await table.set_auto_deal(room_id, guests[0], False)
    clock.advance(timedelta(seconds=10))
    assert not await table.auto_start_hand(room_id)
    # host can still deal manually any time
    await start(room_id, guests[0])
    assert (await view_for(room_id, guests[0]))["hand"]["ordinal"] == 3


async def test_auto_deal_waits_for_two_players():
    room_id, guests, _ = await make_table(2)
    await start(room_id, guests[0])
    await fold_out(room_id, guests)
    await table.leave(room_id, guests[1])
    clock.advance(timedelta(seconds=6))
    assert not await table.auto_start_hand(room_id)
    v = await view_for(room_id, guests[0])
    assert v["hand"] is None and v["next_hand_at"] is not None  # still armed


async def test_long_sit_out_stands_player_up():
    room_id, guests, _ = await make_table(3)
    await table.set_sit_out(room_id, guests[2], True)
    clock.advance(timedelta(minutes=9))
    await rooms.sweep_room(room_id, set())
    v = await view_for(room_id, guests[2])
    assert v["me"]["seat_no"] is not None
    clock.advance(timedelta(minutes=2))
    await rooms.sweep_room(room_id, set())
    v = await view_for(room_id, guests[2])
    assert v["me"]["seat_no"] is None
    row = next(r for r in v["standings"] if r["member_id"] == v["me"]["member_id"])
    assert row["cashed_out"] == 1000 and row["net"] == 0 and not row["seated"]


async def test_result_shows_own_cards_and_net_is_zero_sum():
    room_id, guests, _ = await make_table(3)
    await start(room_id, guests[0])
    cards = {}
    for g in guests:
        v = await view_for(room_id, g)
        cards[g] = v["hand"]["your_cards"]
    folder, v = await actor_guest(room_id, guests)
    await act(room_id, folder, v, "FOLD")
    # mid-hand, chips in the pot still count toward net
    mid = await view_for(room_id, guests[0])
    assert sum(s["net"] for s in mid["seats"]) == 0
    while (await view_for(room_id, guests[0]))["hand"] is not None:
        g, v = await actor_guest(room_id, guests)
        la = v["hand"]["legal_actions"]
        await act(room_id, g, v, "CHECK" if la["can_check"] else "CALL")
    for g in guests:
        v = await view_for(room_id, g)
        assert v["last_hand"]["my_cards"] == cards[g]  # folded player too
        assert v["last_hand"]["seat_members"]
    v = await view_for(room_id, guests[0])
    assert sum(s["net"] for s in v["seats"]) == 0
    assert sum(r["net"] for r in v["standings"]) == 0
    assert v["standings"] == sorted(v["standings"], key=lambda r: -r["net"])
    # spectators never get anyone's folded cards
    spec = await make_guest("spec")
    assert "my_cards" not in (await view_for(room_id, spec))["last_hand"]
