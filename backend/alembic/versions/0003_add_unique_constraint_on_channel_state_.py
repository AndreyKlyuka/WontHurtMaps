"""Add unique constraint on channel_state.channel_id

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-23 23:43:59.348167
"""

from __future__ import annotations

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_unique_constraint("uq_channel_state_channel_id", "channel_state", ["channel_id"])


def downgrade() -> None:
    op.drop_constraint("uq_channel_state_channel_id", "channel_state", type_="unique")
