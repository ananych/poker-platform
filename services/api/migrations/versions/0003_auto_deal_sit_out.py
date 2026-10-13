"""auto-deal and sit-out timestamps

Revision ID: 0003
Revises: 0002
Create Date: 2026-10-13
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "rooms", sa.Column("auto_deal", sa.Boolean(), server_default="true", nullable=False)
    )
    op.add_column("rooms", sa.Column("next_hand_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "table_seats", sa.Column("sitting_out_since", sa.DateTime(timezone=True), nullable=True)
    )
    op.execute(
        "UPDATE table_seats SET sitting_out_since = now() WHERE participation_state = 'SITTING_OUT'"
    )
    op.create_index(
        "ix_hands_live_deadline",
        "hands",
        ["deadline_at"],
        postgresql_where=sa.text("ended_at IS NULL AND deadline_at IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_hands_live_deadline", table_name="hands")
    op.drop_column("table_seats", "sitting_out_since")
    op.drop_column("rooms", "next_hand_at")
    op.drop_column("rooms", "auto_deal")
