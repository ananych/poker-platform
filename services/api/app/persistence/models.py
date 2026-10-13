"""SQLAlchemy models for SDD §6. Money is BIGINT integer chip units with CHECK >= 0."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    pass


Base.metadata.naming_convention = NAMING


def _uuid_pk() -> Mapped[uuid.UUID]:
    return mapped_column(primary_key=True, default=uuid.uuid4)


def _now() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class Guest(Base):
    __tablename__ = "guests"
    guest_id: Mapped[uuid.UUID] = _uuid_pk()
    nickname: Mapped[str] = mapped_column(String(32), nullable=False)  # display only
    created_at: Mapped[datetime] = _now()


class GuestSession(Base):
    __tablename__ = "guest_sessions"
    id: Mapped[uuid.UUID] = _uuid_pk()
    guest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("guests.guest_id"), nullable=False)
    token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    created_at: Mapped[datetime] = _now()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Room(Base):
    __tablename__ = "rooms"
    id: Mapped[uuid.UUID] = _uuid_pk()
    name: Mapped[str | None] = mapped_column(String(64))
    invite_token_hash: Mapped[bytes] = mapped_column(LargeBinary(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    # FK to room_members; use_alter breaks the rooms <-> room_members cycle.
    host_member_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("room_members.id", use_alter=True, name="fk_rooms_host_member")
    )
    status: Mapped[str] = mapped_column(String(24), nullable=False, server_default="OPEN")
    operational_status: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="ACTIVE"
    )
    config_json: Mapped[dict] = mapped_column(JSONB, nullable=False)
    pending_config_json: Mapped[dict | None] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False, server_default="0")
    button_seat: Mapped[int | None] = mapped_column(Integer)
    bb_seat: Mapped[int | None] = mapped_column(Integer)  # BB advances 1 seat per hand (A-01)
    # auto-deal: next hand starts at next_hand_at unless the host paused dealing
    auto_deal: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    next_hand_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    empty_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _now()
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("version >= 0", name="version_nonneg"),
        CheckConstraint("status IN ('OPEN','EMPTY_PENDING_CLOSE','CLOSED')", name="status_enum"),
        CheckConstraint("operational_status IN ('ACTIVE','PAUSED_RECOVERY')", name="op_status"),
        Index("ix_rooms_status", "id", "status"),
    )


class RoomMember(Base):
    __tablename__ = "room_members"
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    guest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("guests.guest_id"), nullable=False)
    joined_at: Mapped[datetime] = _now()
    role: Mapped[str] = mapped_column(String(16), nullable=False, server_default="member")
    ban_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnected_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("room_id", "guest_id", name="uq_room_members_room_guest"),
        CheckConstraint("role IN ('member','spectator')", name="role_enum"),
        Index("ix_room_members_room_joined", "room_id", "joined_at"),
    )


class RoomBan(Base):
    __tablename__ = "room_bans"
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    guest_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("guests.guest_id"), nullable=False)
    banned_by: Mapped[uuid.UUID] = mapped_column(ForeignKey("room_members.id"), nullable=False)
    created_at: Mapped[datetime] = _now()
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        # at most one ACTIVE ban per guest+room
        Index(
            "uq_room_bans_active",
            "room_id",
            "guest_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )


class TableSeat(Base):
    __tablename__ = "table_seats"
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), primary_key=True)
    seat_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("room_members.id"), nullable=False)
    stack: Mapped[int] = mapped_column(BigInteger, nullable=False)
    # participation (WAITING_FOR_BLIND/ACTIVE/SITTING_OUT) stored separately
    # from connectivity and pending departure (SDD §4).
    participation_state: Mapped[str] = mapped_column(
        String(24), nullable=False, server_default="WAITING_FOR_BLIND"
    )
    pending_leave: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    sit_out_next: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    # set while SITTING_OUT; the sweeper stands the player up after a grace period
    sitting_out_since: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("seat_no BETWEEN 1 AND 9", name="seat_range"),
        CheckConstraint("stack >= 0", name="stack_nonneg"),
        CheckConstraint(
            "participation_state IN ('WAITING_FOR_BLIND','ACTIVE','SITTING_OUT')",
            name="participation_enum",
        ),
        UniqueConstraint("room_id", "member_id", name="uq_table_seats_room_member"),
    )


class Hand(Base):
    __tablename__ = "hands"
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    phase: Mapped[str] = mapped_column(String(24), nullable=False)
    button_seat: Mapped[int] = mapped_column(Integer, nullable=False)
    actor_seat: Mapped[int | None] = mapped_column(Integer)
    config_snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)  # immutable
    room_version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hand_snapshot_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    idempotency_key: Mapped[str | None] = mapped_column(String(64))
    started_at: Mapped[datetime] = _now()
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        UniqueConstraint("room_id", "ordinal", name="uq_hands_room_ordinal"),
        UniqueConstraint("room_id", "idempotency_key", name="uq_hands_room_idem"),
        # at most one unfinished hand per room
        Index(
            "uq_hands_one_live_per_room",
            "room_id",
            unique=True,
            postgresql_where=text("ended_at IS NULL"),
        ),
        Index(
            "ix_hands_pending_deadline", "deadline_at", postgresql_where=text("ended_at IS NULL")
        ),
    )


class HandPlayer(Base):
    __tablename__ = "hand_players"
    hand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hands.id"), primary_key=True)
    seat_no: Mapped[int] = mapped_column(Integer, primary_key=True)
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("room_members.id"), nullable=False)
    hole_cards_ciphertext: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    street_contribution: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    total_contribution: Mapped[int] = mapped_column(BigInteger, nullable=False, default=0)
    folded: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    all_in: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    show_status: Mapped[str] = mapped_column(String(16), nullable=False, default="HIDDEN")

    __table_args__ = (
        CheckConstraint(
            "street_contribution >= 0 AND total_contribution >= 0", name="contrib_nonneg"
        ),
    )


class HandEvent(Base):
    __tablename__ = "hand_events"
    id: Mapped[uuid.UUID] = _uuid_pk()
    hand_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("hands.id"), nullable=False)
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    action_id: Mapped[uuid.UUID | None] = mapped_column()
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("room_members.id"))
    event_type: Mapped[str] = mapped_column(String(48), nullable=False)
    public_payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    private_payload_ciphertext: Mapped[bytes | None] = mapped_column(LargeBinary)
    private_to_seat: Mapped[int | None] = mapped_column(Integer)
    version: Mapped[int] = mapped_column(BigInteger, nullable=False)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (
        UniqueConstraint("hand_id", "seq", name="uq_hand_events_hand_seq"),
        Index(
            "uq_hand_events_actor_action",
            "actor_id",
            "action_id",
            unique=True,
            postgresql_where=text("action_id IS NOT NULL"),
        ),
    )


class ActionResult(Base):
    """Durable action dedup (SDD §1.2, §8): retries return the original outcome."""

    __tablename__ = "action_results"
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), primary_key=True)
    actor_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("room_members.id"), primary_key=True)
    action_id: Mapped[uuid.UUID] = mapped_column(primary_key=True)
    result: Mapped[dict] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = _now()


class ChipLedger(Base):
    __tablename__ = "chip_ledger"
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("room_members.id"), nullable=False)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    reference_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    created_at: Mapped[datetime] = _now()
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("amount >= 0", name="amount_nonneg"),
        CheckConstraint("type IN ('BUY_IN','TOP_UP','CASH_OUT','CORRECTION')", name="type_enum"),
        Index("ix_chip_ledger_member_created", "member_id", "created_at"),
    )


class TopupRequest(Base):
    __tablename__ = "topup_requests"
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("room_members.id"), nullable=False)
    amount: Mapped[int] = mapped_column(BigInteger, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="REQUESTED")
    approved_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("room_members.id"))
    created_at: Mapped[datetime] = _now()
    applied_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        CheckConstraint("amount > 0", name="amount_pos"),
        CheckConstraint(
            "status IN ('REQUESTED','APPROVED','APPLIED','REJECTED')", name="status_enum"
        ),
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    id: Mapped[uuid.UUID] = _uuid_pk()
    room_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("rooms.id"), nullable=False)
    member_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("room_members.id"), nullable=False)
    body: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = _now()

    __table_args__ = (Index("ix_chat_messages_room_created", "room_id", "created_at"),)
