"""add unique constraint on unrecognized_tokens(city_id, token)

Revision ID: 56f5d11e7dbe
Revises: 0003
Create Date: 2026-04-05 23:50:25.528160
"""

from __future__ import annotations

from alembic import op

revision: str = "56f5d11e7dbe"
down_revision: str | None = "0003"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_unique_constraint(
        "uq_unrecognized_tokens_city_token",
        "unrecognized_tokens",
        ["city_id", "token"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_unrecognized_tokens_city_token",
        "unrecognized_tokens",
        type_="unique",
    )
