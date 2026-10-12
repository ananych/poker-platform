"""REST API v1 — rooms (SDD §7). Chip amounts are strict integers (no floats).

In-game actions should use the WebSocket; POST /actions exists for tooling and
goes through exactly the same serialized coordinator (never a bypass).
"""

from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, Header, Query, Request
from pydantic import BaseModel, Field, StrictBool, StrictInt

from app.api.deps import require_session
from app.persistence.db import new_session
from app.realtime.gateway import gateway
from app.services import chat, history, rooms, table
from app.services.guests import SessionContext
from app.services.views import load_bundle, render

router = APIRouter(prefix="/rooms", tags=["rooms"])


def gid(ctx: SessionContext) -> uuid.UUID:
    return ctx.guest.guest_id


class CreateRoomIn(BaseModel):
    password: str = Field(min_length=4, max_length=128)
    name: str | None = Field(default=None, max_length=64)
    sb: StrictInt
    bb: StrictInt
    min_buyin: StrictInt
    max_buyin: StrictInt


class JoinIn(BaseModel):
    password: str = Field(max_length=128)
    invite_token: str = Field(max_length=128)


class BuyinIn(BaseModel):
    buyin: StrictInt


class SitOutIn(BaseModel):
    sit_out: StrictBool


class TopupIn(BaseModel):
    amount: StrictInt


class ApproveIn(BaseModel):
    approve: StrictBool


class StartHandIn(BaseModel):
    expected_room_version: StrictInt | None = None
    idempotency_key: str | None = Field(default=None, max_length=64)


class ConfigIn(BaseModel):
    sb: StrictInt | None = None
    bb: StrictInt | None = None
    min_buyin: StrictInt | None = None
    max_buyin: StrictInt | None = None


class TransferIn(BaseModel):
    member_id: uuid.UUID


class ActionIn(BaseModel):
    action_id: uuid.UUID
    hand_id: uuid.UUID
    expected_room_version: StrictInt
    action: str = Field(max_length=16)
    raise_to: StrictInt | None = None


@router.post("")
async def create_room(body: CreateRoomIn, ctx: SessionContext = Depends(require_session)):
    return await rooms.create_room(
        gid(ctx),
        password=body.password,
        name=body.name,
        config=body.model_dump(include={"sb", "bb", "min_buyin", "max_buyin"}),
    )


@router.post("/{room_id}/join")
async def join(
    room_id: uuid.UUID,
    body: JoinIn,
    request: Request,
    ctx: SessionContext = Depends(require_session),
):
    ip = request.client.host if request.client else "?"
    return await rooms.join_room(
        room_id, gid(ctx), invite_token=body.invite_token, password=body.password, client_ip=ip
    )


@router.get("/{room_id}")
async def get_room(room_id: uuid.UUID, ctx: SessionContext = Depends(require_session)):
    async with new_session() as db:
        member = await table.member_of(db, room_id, gid(ctx))
        bundle = await load_bundle(db, room_id)
    assert bundle is not None
    return render(bundle, member, gateway.connected_members(room_id))


@router.post("/{room_id}/seats/{seat_no}")
async def claim_seat(
    room_id: uuid.UUID, seat_no: int, body: BuyinIn, ctx: SessionContext = Depends(require_session)
):
    return await table.claim_seat(room_id, gid(ctx), seat_no, body.buyin)


@router.post("/{room_id}/sit-out")
async def sit_out(
    room_id: uuid.UUID, body: SitOutIn, ctx: SessionContext = Depends(require_session)
):
    return await table.set_sit_out(room_id, gid(ctx), body.sit_out)


@router.post("/{room_id}/leave")
async def leave(room_id: uuid.UUID, ctx: SessionContext = Depends(require_session)):
    return await table.leave(room_id, gid(ctx))


@router.post("/{room_id}/topups")
async def request_topup(
    room_id: uuid.UUID, body: TopupIn, ctx: SessionContext = Depends(require_session)
):
    return await rooms.request_topup(room_id, gid(ctx), body.amount)


@router.post("/{room_id}/topups/{request_id}/approve")
async def approve_topup(
    room_id: uuid.UUID,
    request_id: uuid.UUID,
    body: ApproveIn,
    ctx: SessionContext = Depends(require_session),
):
    return await rooms.decide_topup(room_id, gid(ctx), request_id, body.approve)


@router.post("/{room_id}/start-hand")
async def start_hand(
    room_id: uuid.UUID,
    body: StartHandIn | None = None,
    idempotency_key: str | None = Header(default=None, max_length=64),
    ctx: SessionContext = Depends(require_session),
):
    body = body or StartHandIn()
    return await table.start_next_hand(
        room_id,
        gid(ctx),
        expected_version=body.expected_room_version,
        idempotency_key=body.idempotency_key or idempotency_key,
    )


@router.post("/{room_id}/resume")
async def resume(room_id: uuid.UUID, ctx: SessionContext = Depends(require_session)):
    return await table.resume(room_id, gid(ctx))


@router.patch("/{room_id}/config")
async def update_config(
    room_id: uuid.UUID, body: ConfigIn, ctx: SessionContext = Depends(require_session)
):
    return await rooms.update_config(room_id, gid(ctx), body.model_dump(exclude_none=True))


@router.post("/{room_id}/members/{member_id}/ban")
async def ban(
    room_id: uuid.UUID, member_id: uuid.UUID, ctx: SessionContext = Depends(require_session)
):
    return await rooms.kick(room_id, gid(ctx), member_id, ban=True)


@router.post("/{room_id}/members/{member_id}/kick")
async def kick(
    room_id: uuid.UUID, member_id: uuid.UUID, ctx: SessionContext = Depends(require_session)
):
    return await rooms.kick(room_id, gid(ctx), member_id, ban=False)


@router.delete("/{room_id}/bans/{member_id}")
async def unban(
    room_id: uuid.UUID, member_id: uuid.UUID, ctx: SessionContext = Depends(require_session)
):
    return await rooms.unban(room_id, gid(ctx), member_id)


@router.post("/{room_id}/invite")
async def rotate_invite(room_id: uuid.UUID, ctx: SessionContext = Depends(require_session)):
    return await rooms.rotate_invite(room_id, gid(ctx))


@router.post("/{room_id}/transfer-host")
async def transfer_host(
    room_id: uuid.UUID, body: TransferIn, ctx: SessionContext = Depends(require_session)
):
    return await rooms.transfer_host(room_id, gid(ctx), body.member_id)


@router.get("/{room_id}/ledger")
async def ledger(room_id: uuid.UUID, ctx: SessionContext = Depends(require_session)):
    return await rooms.ledger_view(room_id, gid(ctx))


@router.post("/{room_id}/actions")
async def action(
    room_id: uuid.UUID, body: ActionIn, ctx: SessionContext = Depends(require_session)
):
    return await table.player_action(
        room_id,
        gid(ctx),
        action_id=body.action_id,
        hand_id=body.hand_id,
        expected_version=body.expected_room_version,
        action=body.action,
        raise_to=body.raise_to,
    )


class ChatIn(BaseModel):
    body: str = Field(min_length=1, max_length=2000)


@router.get("/{room_id}/hands")
async def hands(
    room_id: uuid.UUID,
    cursor: int | None = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=50),
    ctx: SessionContext = Depends(require_session),
):
    return await history.list_hands(room_id, gid(ctx), cursor=cursor, limit=limit)


@router.get("/{room_id}/hands/{hand_id}")
async def hand_replay(
    room_id: uuid.UUID, hand_id: uuid.UUID, ctx: SessionContext = Depends(require_session)
):
    return await history.replay(room_id, gid(ctx), hand_id)


@router.get("/{room_id}/chat")
async def chat_recent(
    room_id: uuid.UUID,
    before: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    ctx: SessionContext = Depends(require_session),
):
    return {"messages": await chat.recent(room_id, gid(ctx), before=before, limit=limit)}


@router.post("/{room_id}/chat")
async def chat_post(
    room_id: uuid.UUID, body: ChatIn, ctx: SessionContext = Depends(require_session)
):
    msg = await chat.post_message(room_id, gid(ctx), body.body)
    await gateway.broadcast(room_id, "chat.message", msg)
    return msg
