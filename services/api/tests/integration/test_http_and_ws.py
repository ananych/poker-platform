"""REST contract (§7) and WebSocket gateway (§8) end-to-end tests."""

import asyncio
import json
import uuid
from datetime import timedelta

import pytest

from app.persistence.db import new_session
from app.realtime.gateway import CLOSE_FORBIDDEN, CLOSE_UNAUTHORIZED, gateway
from app.services import rooms, table
from app.services.guests import create_guest_session
from tests.integration.conftest import TEST_DB
from tests.integration.factory import PASSWORD, make_table, view_for

pytestmark = [
    pytest.mark.skipif(not TEST_DB, reason="POKER_TEST_DATABASE_URL not set"),
    pytest.mark.usefixtures("app"),
]


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------
async def session(c, nick):
    r = await c.post("/api/v1/guests/session", json={"nickname": nick})
    assert r.status_code == 200
    return r.json()


async def test_rest_full_flow(make_client):
    host, alice, bob = make_client(), make_client(), make_client()
    await session(host, "Host")
    await session(alice, "Alice")
    await session(bob, "Bob")

    r = await host.post(
        "/api/v1/rooms",
        json={
            "password": "pw-1234",
            "name": "Fri",
            "sb": 5,
            "bb": 10,
            "min_buyin": 200,
            "max_buyin": 2000,
        },
    )
    assert r.status_code == 200, r.text
    room = r.json()
    rid, invite = room["room_id"], room["invite_token"]
    assert "password" not in json.dumps(room).lower().replace("invite", "")

    # wrong password / missing invite
    r = await alice.post(
        f"/api/v1/rooms/{rid}/join", json={"password": "nope", "invite_token": invite}
    )
    assert r.status_code == 403 and r.json()["error"]["code"] == "INVALID_PASSWORD"
    r = await alice.post(
        f"/api/v1/rooms/{rid}/join", json={"password": "pw-1234", "invite_token": "x"}
    )
    assert r.json()["error"]["code"] == "UNAUTHORIZED"
    # non-member cannot see the room
    r = await alice.get(f"/api/v1/rooms/{rid}")
    assert r.status_code == 403 and r.json()["error"]["code"] == "NOT_MEMBER"

    for c in (alice, bob):
        r = await c.post(
            f"/api/v1/rooms/{rid}/join", json={"password": "pw-1234", "invite_token": invite}
        )
        assert r.status_code == 200

    # chips must be strict integers
    r = await alice.post(f"/api/v1/rooms/{rid}/seats/2", json={"buyin": 500.5})
    assert r.status_code == 422
    r = await alice.post(f"/api/v1/rooms/{rid}/seats/2", json={"buyin": 5000})
    assert r.json()["error"]["code"] == "INVALID_BUYIN"
    for c, n in ((host, 1), (alice, 2), (bob, 5)):
        r = await c.post(f"/api/v1/rooms/{rid}/seats/{n}", json={"buyin": 1000})
        assert r.status_code == 200, r.text
    r = await bob.post(f"/api/v1/rooms/{rid}/seats/1", json={"buyin": 1000})
    assert r.json()["error"]["code"] == "ALREADY_SEATED"

    r = await alice.post(f"/api/v1/rooms/{rid}/start-hand", json={})
    assert r.json()["error"]["code"] == "NOT_HOST"
    r = await host.post(
        f"/api/v1/rooms/{rid}/start-hand", json={}, headers={"Idempotency-Key": "h1"}
    )
    assert r.status_code == 200, r.text
    r2 = await host.post(
        f"/api/v1/rooms/{rid}/start-hand", json={}, headers={"Idempotency-Key": "h1"}
    )
    assert r2.json()["hand_id"] == r.json()["hand_id"]

    # play: everybody calls/checks down
    clients = {"Host": host, "Alice": alice, "Bob": bob}
    for _ in range(40):
        views = {n: (await c.get(f"/api/v1/rooms/{rid}")).json() for n, c in clients.items()}
        hv = views["Host"]["hand"]
        if hv is None:
            break
        # privacy: nobody sees others' cards
        mine = {n: set(v["hand"]["your_cards"]) for n, v in views.items()}
        for n, v in views.items():
            for other, cards in mine.items():
                if other != n:
                    assert not any(f'"{c}"' in json.dumps(v) for c in cards)
        actor = next(n for n, v in views.items() if v["hand"].get("legal_actions"))
        v = views[actor]
        la = v["hand"]["legal_actions"]
        r = await clients[actor].post(
            f"/api/v1/rooms/{rid}/actions",
            json={
                "action_id": str(uuid.uuid4()),
                "hand_id": v["hand"]["hand_id"],
                "expected_room_version": v["room_version"],
                "action": "CHECK" if la["can_check"] else "CALL",
            },
        )
        assert r.status_code == 200, r.text
    final = (await host.get(f"/api/v1/rooms/{rid}")).json()
    assert final["hand"] is None and final["last_hand"]["completed"]["pots"]
    assert sum(s["stack"] for s in final["seats"]) == 3000

    led = (await alice.get(f"/api/v1/rooms/{rid}/ledger")).json()
    assert sum(row["net"] for row in led["summary"]) == 0
    me = (await alice.get("/api/v1/me")).json()
    assert me["rooms"][0]["room_id"] == rid


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
class Disconnect(Exception):
    pass


Disconnect.__name__ = "WebSocketDisconnect"


class FakeWS:
    def __init__(self, token: str | None, origin: str | None = "http://localhost:3000"):
        self.headers = {"origin": origin} if origin else {}
        self.cookies = {"poker_session": token} if token else {}
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.sent: list[dict] = []
        self.accepted = False
        self.closed_code: int | None = None

    async def accept(self):
        self.accepted = True

    async def close(self, code: int = 1000):
        self.closed_code = code
        await self.inbox.put(None)

    async def send_text(self, data: str):
        self.sent.append(json.loads(data))

    async def receive_text(self) -> str:
        m = await self.inbox.get()
        if m is None:
            raise Disconnect()
        return m

    def of(self, etype):
        return [m for m in self.sent if m["type"] == etype]


async def wait_until(pred, timeout=3.0):
    for _ in range(int(timeout / 0.02)):
        if pred():
            return
        await asyncio.sleep(0.02)
    raise AssertionError("condition not met")


async def token_for(guest_id) -> str:
    # issue an extra session token for an existing guest
    from app.persistence.models import Guest
    from app.services.guests import _issue

    async with new_session() as db, db.begin():
        g = await db.get(Guest, guest_id)
        _, tok = await _issue(db, g, timedelta(days=1))
        return tok


async def connect(room_id, token, **kw):
    ws = FakeWS(token, **kw)
    task = asyncio.create_task(gateway.handle(ws, room_id))
    return ws, task


async def test_ws_rejects_unauthenticated_bad_origin_and_non_members():
    room_id, guests, _ = await make_table(2)
    ws, t = await connect(room_id, None)
    await t
    assert ws.closed_code == CLOSE_UNAUTHORIZED and not ws.accepted
    tok = await token_for(guests[0])
    ws, t = await connect(room_id, tok, origin="https://evil.example")
    await t
    assert ws.closed_code == CLOSE_FORBIDDEN and not ws.accepted
    async with new_session() as db, db.begin():
        ctx, outsider = await create_guest_session(db, "out", timedelta(days=1))
    ws, t = await connect(room_id, outsider)
    await t
    assert ws.closed_code == CLOSE_FORBIDDEN


async def test_ws_play_privacy_and_ban():
    room_id, guests, invite = await make_table(3)
    spectator = guests[0]  # host is seated; add a pure spectator
    from tests.integration.factory import make_guest

    spec = await make_guest("spec")
    await rooms.join_room(
        room_id, spec, invite_token=invite["invite_token"], password=PASSWORD, client_ip="s"
    )
    socks = {}
    for g in [*guests, spec]:
        socks[g] = await connect(room_id, await token_for(g))
    for ws, _ in socks.values():
        await wait_until(lambda ws=ws: ws.of("room.state"))
    assert all(ws.accepted for ws, _ in socks.values())

    await table.start_next_hand(room_id, spectator)
    for g in guests:
        ws = socks[g][0]
        await wait_until(lambda ws=ws: ws.of("hand.your_cards"))
        assert len(ws.of("hand.your_cards")) == 1
    spec_ws = socks[spec][0]
    await wait_until(lambda: any(m["payload"].get("hand") for m in spec_ws.of("room.state")))
    assert not spec_ws.of("hand.your_cards")
    hole = {
        c for g in guests for c in socks[g][0].of("hand.your_cards")[0]["payload"]["hole_cards"]
    }
    assert not any(f'"{c}"' in json.dumps(spec_ws.sent) for c in hole)

    # actor sends an action over the socket
    state = socks[guests[0]][0].of("room.state")[-1]["payload"]
    actor_seat = state["hand"]["actor_seat"]
    seat_of_guest = {g: (await view_for(room_id, g))["me"]["seat_no"] for g in guests}
    actor = next(g for g in guests if seat_of_guest[g] == actor_seat)
    aws = socks[actor][0]
    v = await view_for(room_id, actor)
    cmd = {
        "kind": "command",
        "type": "player.action",
        "action_id": str(uuid.uuid4()),
        "hand_id": v["hand"]["hand_id"],
        "expected_room_version": v["room_version"],
        "payload": {"action": "CALL"},
    }
    await aws.inbox.put(json.dumps(cmd))
    await wait_until(lambda: aws.of("action.result"))
    assert aws.of("action.result")[0]["payload"]["accepted"] is True
    # duplicate delivery returns the original result
    await aws.inbox.put(json.dumps(cmd))
    await wait_until(lambda: len(aws.of("action.result")) == 2)
    r1, r2 = aws.of("action.result")
    assert r2["payload"]["replayed"] and r1["room_version"] == r2["room_version"]
    # stale command is rejected with an error code, not applied
    await aws.inbox.put(json.dumps({**cmd, "action_id": str(uuid.uuid4())}))
    await wait_until(lambda: len(aws.of("action.result")) == 3)
    assert aws.of("action.result")[2]["payload"]["error"]["code"] in (
        "STALE_VERSION",
        "NOT_YOUR_TURN",
    )
    # versions observed by a client are monotonic
    vs = [m["room_version"] for m in spec_ws.of("room.state")]
    assert vs == sorted(vs)

    # ban -> socket closed
    victim = guests[2]
    vm = uuid.UUID((await view_for(room_id, victim))["me"]["member_id"])
    await rooms.kick(room_id, guests[0], vm, ban=True)
    vws, vtask = socks[victim]
    await wait_until(lambda: vws.closed_code == CLOSE_FORBIDDEN)
    await vtask

    for ws, t in socks.values():
        if not t.done():
            await ws.close()
            await t
    v = await view_for(room_id, guests[0])
    assert v["status"] == "EMPTY_PENDING_CLOSE"


async def test_ws_malformed_and_ping():
    room_id, guests, _ = await make_table(2)
    ws, t = await connect(room_id, await token_for(guests[1]))
    await wait_until(lambda: ws.accepted)
    await ws.inbox.put("not json")
    await ws.inbox.put(json.dumps({"kind": "command", "type": "ping"}))
    await ws.inbox.put("x" * 10000)
    await wait_until(lambda: ws.of("pong") and len(ws.of("error")) == 2)
    await ws.close()
    await t
