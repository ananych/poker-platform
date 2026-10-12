"""30-user capacity gate (SDD §13.2/§13.3): scripted play over real HTTP + WebSocket.

    python scripts/loadtest.py --base http://localhost:8000 --users 30 --per-room 6 --seconds 60

Each room: 1 host + (per-room - 1) guests, everyone seated; the host starts hands
continuously; each player answers its turn with a random legal action taken from the
server projection. Reports action round-trip latency (p50/p95) and checks:
  * no game-state divergence (all clients of a room converge to the same room_version
    as the REST view),
  * virtual chip conservation per room (sum of ledger nets == 0 between hands),
  * no unexpected errors (STALE_VERSION races are counted, not fatal).
Exit code 1 if any gate fails.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import statistics
import time
import uuid
from collections import Counter

import httpx
import websockets

ORIGIN = "http://localhost:3000"


class Player:
    def __init__(self, base: str, name: str, rng: random.Random) -> None:
        self.base, self.name, self.rng = base, name, rng
        self.http = httpx.AsyncClient(
            base_url=base, headers={"X-Poker-CSRF": "1", "Origin": ORIGIN}, timeout=15
        )
        self.view: dict | None = None
        self.version = -1
        self.pending: dict[str, float] = {}
        self.latencies: list[float] = []
        self.errors: Counter[str] = Counter()
        self.ws = None

    async def session(self) -> None:
        (
            await self.http.post("/api/v1/guests/session", json={"nickname": self.name})
        ).raise_for_status()

    async def connect(self, room_id: str) -> None:
        cookie = self.http.cookies.get("poker_session")
        url = self.base.replace("http", "ws") + f"/ws/rooms/{room_id}"
        self.ws = await websockets.connect(
            url, additional_headers={"Cookie": f"poker_session={cookie}", "Origin": ORIGIN}
        )

    async def listen(self, stop: asyncio.Event) -> None:
        assert self.ws is not None
        try:
            async for raw in self.ws:
                m = json.loads(raw)
                if m["type"] == "room.state" and m["room_version"] >= self.version:
                    self.version, self.view = m["room_version"], m["payload"]
                    await self.maybe_act()
                elif m["type"] == "action.result":
                    p = m["payload"]
                    t0 = self.pending.pop(p.get("action_id"), None)
                    if t0 is not None:
                        self.latencies.append(time.perf_counter() - t0)
                    if not p.get("accepted"):
                        self.errors[p["error"]["code"]] += 1
                        await self.ws.send(json.dumps({"kind": "command", "type": "room.sync"}))
                    else:
                        await self.maybe_act()  # state may have arrived while pending
                if stop.is_set():
                    return
        except websockets.ConnectionClosed:
            pass

    async def maybe_act(self) -> None:
        v = self.view
        h = v and v.get("hand")
        la = h and h.get("legal_actions")
        if not la or self.pending:
            return
        await asyncio.sleep(self.rng.uniform(0.02, 0.15))  # human-ish think time
        opts = (
            [("FOLD", None)]
            + [("CHECK", None)] * 4 * la["can_check"]
            + [("CALL", None)] * 4 * (la["call_amount"] > 0)
        )
        if la["can_bet"] or la["can_raise"]:
            hi = min(la["max_raise_to"], la["min_raise_to"] * 3)
            opts.append(
                (
                    "BET" if la["can_bet"] else "RAISE",
                    self.rng.randint(la["min_raise_to"], max(la["min_raise_to"], hi)),
                )
            )
            if self.rng.random() < 0.05:
                opts.append(("ALL_IN", None))
        action, amt = self.rng.choice(opts)
        aid = str(uuid.uuid4())
        payload = {"action": action} | ({"raise_to": amt} if amt is not None else {})
        self.pending[aid] = time.perf_counter()
        await self.ws.send(
            json.dumps(
                {
                    "kind": "command",
                    "type": "player.action",
                    "action_id": aid,
                    "hand_id": h["hand_id"],
                    "expected_room_version": v["room_version"],
                    "payload": payload,
                }
            )
        )


async def run_room(base: str, idx: int, size: int, seconds: float, rng: random.Random):
    players = [Player(base, f"r{idx}p{i}", random.Random(rng.random())) for i in range(size)]
    for p in players:
        await p.session()
    host = players[0]
    r = (
        await host.http.post(
            "/api/v1/rooms",
            json={
                "password": "load-test",
                "name": f"load-{idx}",
                "sb": 1,
                "bb": 2,
                "min_buyin": 100,
                "max_buyin": 400,
            },
        )
    ).json()
    rid = r["room_id"]
    for p in players[1:]:
        (
            await p.http.post(
                f"/api/v1/rooms/{rid}/join",
                json={"password": "load-test", "invite_token": r["invite_token"]},
            )
        ).raise_for_status()
    for n, p in enumerate(players, start=1):
        (
            await p.http.post(f"/api/v1/rooms/{rid}/seats/{n}", json={"buyin": 200})
        ).raise_for_status()
    stop = asyncio.Event()
    for p in players:
        await p.connect(rid)
    listeners = [asyncio.create_task(p.listen(stop)) for p in players]

    hands, start_errors = 0, Counter()
    t_end = time.time() + seconds
    while time.time() < t_end:
        v = (await host.http.get(f"/api/v1/rooms/{rid}")).json()
        if v["hand"] is None:
            # top up busted players so play continues
            for s in v["seats"]:
                if s["stack"] < 2:
                    owner = next(
                        p for p in players if p.view and p.view["me"]["member_id"] == s["member_id"]
                    )
                    q = await owner.http.post(f"/api/v1/rooms/{rid}/topups", json={"amount": 200})
                    if q.status_code == 200:
                        await host.http.post(
                            f"/api/v1/rooms/{rid}/topups/{q.json()['request_id']}/approve",
                            json={"approve": True},
                        )
            res = await host.http.post(
                f"/api/v1/rooms/{rid}/start-hand", json={"expected_room_version": v["room_version"]}
            )
            if res.status_code == 200:
                hands += 1
            else:
                start_errors[res.json()["error"]["code"]] += 1
        await asyncio.sleep(0.2)

    # let the last hand finish (actions keep flowing), then stop
    for _ in range(100):
        if (await host.http.get(f"/api/v1/rooms/{rid}")).json()["hand"] is None:
            break
        await asyncio.sleep(0.2)
    await asyncio.sleep(0.5)
    final = (await host.http.get(f"/api/v1/rooms/{rid}")).json()
    ledger = (await host.http.get(f"/api/v1/rooms/{rid}/ledger")).json()
    stop.set()
    for p in players:
        await p.ws.close()
    for t in listeners:
        t.cancel()
    versions = {p.version for p in players}
    return {
        "room": rid,
        "hands": hands,
        "start_errors": dict(start_errors),
        "final_version": final["room_version"],
        "client_versions": sorted(versions),
        "converged": versions == {final["room_version"]},
        "ledger_net_sum": sum(x["net"] for x in ledger["summary"]),
        "live_hand_at_end": final["hand"] is not None,
        "latencies": [lat for p in players for lat in p.latencies],
        "errors": sum((p.errors for p in players), Counter()),
    }


def pct(xs: list[float], q: float) -> float:
    s = sorted(xs)
    return s[min(len(s) - 1, int(round(q / 100 * (len(s) - 1))))] * 1000 if s else float("nan")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--users", type=int, default=30)
    ap.add_argument("--per-room", type=int, default=6)
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--seed", type=int, default=1)
    a = ap.parse_args()
    rng = random.Random(a.seed)
    rooms = max(1, a.users // a.per_room)
    t0 = time.time()
    results = await asyncio.gather(
        *[
            run_room(a.base, i, a.per_room, a.seconds, random.Random(rng.random()))
            for i in range(rooms)
        ]
    )
    lat = [x for r in results for x in r["latencies"]]
    errors = sum((r["errors"] for r in results), Counter())
    ok = True
    print(f"users={rooms * a.per_room} rooms={rooms} duration={time.time() - t0:.0f}s")
    for r in results:
        print(
            f"  room {r['room'][:8]} hands={r['hands']} v={r['final_version']} "
            f"converged={r['converged']} ledger_net_sum={r['ledger_net_sum']} "
            f"start_errors={r['start_errors']}"
        )
        ok &= r["converged"] and r["ledger_net_sum"] == 0 and not r["live_hand_at_end"]
    print(
        f"actions={len(lat)} p50={pct(lat, 50):.1f}ms p95={pct(lat, 95):.1f}ms "
        f"max={pct(lat, 100):.1f}ms mean={statistics.mean(lat) * 1000 if lat else 0:.1f}ms"
    )
    print(f"rejected actions: {dict(errors)} (STALE_VERSION/NOT_YOUR_TURN races are expected)")
    unexpected = {
        k: v
        for k, v in errors.items()
        if k not in ("STALE_VERSION", "NOT_YOUR_TURN", "DEADLINE_EXPIRED")
    }
    ok &= not unexpected and sum(r["hands"] for r in results) > 0
    print("CAPACITY GATE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
