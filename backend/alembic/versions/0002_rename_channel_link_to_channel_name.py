"""Rename channel_state.channel_link to channel_name

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-23
"""

from __future__ import annotations

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.alter_column("channel_state", "channel_link", new_column_name="channel_name")


def downgrade() -> None:
    op.alter_column("channel_state", "channel_name", new_column_name="channel_link")
