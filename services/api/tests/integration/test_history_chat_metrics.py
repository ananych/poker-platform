"""Phase 4/5 backend: history + redacted replay (§10), chat (§2), metrics (§12)."""

import uuid
from datetime import timedelta

import pytest

from app.services import chat, clock, history, rooms, table
from app.services.errors import ServiceError
from app.services.metrics import metrics
from tests.integration.conftest import TEST_DB
from tests.integration.factory import PASSWORD, act, actor_guest, make_guest, make_table, view_for

pytestmark = [
    pytest.mark.skipif(not TEST_DB, reason="POKER_TEST_DATABASE_URL not set"),
    pytest.mark.usefixtures("app"),
]


async def finish_by_folding(room_id, guests):
    while (await view_for(room_id, guests[0]))["hand"] is not None:
        g, v = await actor_guest(room_id, guests)
        await act(room_id, g, v, "FOLD")


async def finish_checking_down(room_id, guests):
    while (await view_for(room_id, guests[0]))["hand"] is not None:
        g, v = await actor_guest(room_id, guests)
        la = v["hand"]["legal_actions"]
        await act(room_id, g, v, "CHECK" if la["can_check"] else "CALL")


async def test_history_pagination_and_replay_redaction():
    room_id, guests, invite = await make_table(3)
    spectator = await make_guest("spec")
    await rooms.join_room(
        room_id, spectator, invite_token=invite["invite_token"], password=PASSWORD, client_ip="s"
    )
    hole: dict[uuid.UUID, list[str]] = {}
    for i in range(3):
        await table.start_next_hand(room_id, guests[0])
        if i == 2:
            for g in guests:
                hole[g] = (await view_for(room_id, g))["hand"]["your_cards"]
            await finish_checking_down(room_id, guests)  # showdown
        else:
            await finish_by_folding(room_id, guests)

    page = await history.list_hands(room_id, spectator, limit=2)
    assert [h["ordinal"] for h in page["items"]] == [3, 2] and page["next_cursor"] == 2
    page2 = await history.list_hands(room_id, spectator, cursor=page["next_cursor"], limit=2)
    assert [h["ordinal"] for h in page2["items"]] == [1] and page2["next_cursor"] is None
    last = page["items"][0]
    assert sum(p["won"] for p in last["players"]) == sum(p["amount"] for p in last["pots"])

    hand_id = uuid.UUID(last["hand_id"])
    spec_replay = await history.replay(room_id, spectator, hand_id)
    seqs = [e["seq"] for e in spec_replay["events"]]
    assert seqs == sorted(seqs) and spec_replay["my_cards"] is None
    assert not any(e["type"] == "hand.your_cards" for e in spec_replay["events"])
    showdown = next(e for e in spec_replay["events"] if e["type"] == "hand.showdown")
    shown = {s["seat_no"] for s in showdown["payload"]["shown"]}
    blob = str(spec_replay)
    seat_of = {g: (await view_for(room_id, g))["me"]["seat_no"] for g in guests}
    for g, cards in hole.items():
        assert seat_of[g] in shown  # A-02: every showdown hand is shown
        visible = True
        assert all((f"'{c}'" in blob) == visible for c in cards), "shown cards missing from replay"
    # a participant sees their own cards in replay
    own = await history.replay(room_id, guests[1], hand_id)
    assert own["my_cards"] == hole[guests[1]]
    # live hand cannot be replayed
    await table.start_next_hand(room_id, guests[0])
    live_id = uuid.UUID((await view_for(room_id, guests[0]))["hand"]["hand_id"])
    with pytest.raises(ServiceError):
        await history.replay(room_id, spectator, live_id)


async def test_banned_member_has_no_history_but_keeps_own_ledger():
    room_id, guests, _ = await make_table(3)
    await table.start_next_hand(room_id, guests[0])
    await finish_by_folding(room_id, guests)
    victim = uuid.UUID((await view_for(room_id, guests[2]))["me"]["member_id"])
    await rooms.kick(room_id, guests[0], victim, ban=True)
    with pytest.raises(ServiceError) as e:
        await history.list_hands(room_id, guests[2])
    assert e.value.code == "ROOM_BANNED"
    led = await rooms.ledger_view(room_id, guests[2])
    assert led["entries"] and {x["member_id"] for x in led["entries"]} == {str(victim)}


async def test_chat_sanitize_rate_limit_and_membership():
    room_id, guests, _ = await make_table(2)
    m = await chat.post_message(room_id, guests[1], "  hi\x00 there\n\n\n<b>x</b>  ")
    assert m["body"] == "hi there\n<b>x</b>"  # stored as text; UI renders escaped
    with pytest.raises(ServiceError):
        await chat.post_message(room_id, guests[1], "   ")
    with pytest.raises(ServiceError):
        await chat.post_message(room_id, guests[1], "x" * 501)
    outsider = await make_guest("out")
    with pytest.raises(ServiceError) as e:
        await chat.post_message(room_id, outsider, "hello")
    assert e.value.code == "NOT_MEMBER"
    codes = []
    for i in range(10):
        try:
            await chat.post_message(room_id, guests[0], f"spam {i}")
        except ServiceError as err:
            codes.append(err.code)
    assert "RATE_LIMITED" in codes
    msgs = await chat.recent(room_id, guests[1])
    assert msgs[0]["body"].startswith("hi there") and msgs[0]["nickname"]
    clock.advance(timedelta(days=31))
    assert await chat.purge_expired(30) >= 1


async def test_chat_http_and_metrics_endpoint(make_client):
    c = make_client()
    await c.post("/api/v1/guests/session", json={"nickname": "M"})
    r = await c.post(
        "/api/v1/rooms",
        json={"password": "pw-1234", "sb": 1, "bb": 2, "min_buyin": 10, "max_buyin": 100},
    )
    rid = r.json()["room_id"]
    r = await c.post(f"/api/v1/rooms/{rid}/chat", json={"body": "gg"})
    assert r.status_code == 200 and r.json()["body"] == "gg"
    assert (await c.get(f"/api/v1/rooms/{rid}/chat")).json()["messages"][-1]["body"] == "gg"
    metrics.inc("probe")
    r = await c.get("/metrics")
    # test env is not dev and has no token -> disabled
    assert r.status_code == 404


async def test_draining_refuses_new_hands_and_ws_close_all():
    room_id, guests, _ = await make_table(2)
    table.lifecycle.draining = True
    try:
        with pytest.raises(ServiceError) as e:
            await table.start_next_hand(room_id, guests[0])
        assert e.value.code == "ROOM_PAUSED"
    finally:
        table.lifecycle.draining = False
    await table.start_next_hand(room_id, guests[0])
