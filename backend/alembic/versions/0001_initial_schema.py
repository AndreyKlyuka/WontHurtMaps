"""Initial schema with all tables and Odesa seed data

Revision ID: 0001
Revises:
Create Date: 2026-03-23 00:00:00.000000
"""

from __future__ import annotations

import geoalchemy2
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    # PostGIS extension — idempotent, safe on re-run
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")

    # ------------------------------------------------------------------
    # cities
    # ------------------------------------------------------------------
    op.create_table(
        "cities",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_ru", sa.String(100), nullable=False),
        sa.Column("bbox_north", sa.Float(), nullable=False),
        sa.Column("bbox_south", sa.Float(), nullable=False),
        sa.Column("bbox_east", sa.Float(), nullable=False),
        sa.Column("bbox_west", sa.Float(), nullable=False),
        sa.Column("default_zoom", sa.Integer(), nullable=False, server_default="13"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name", name="uq_cities_name"),
    )

    # ------------------------------------------------------------------
    # posts
    # ------------------------------------------------------------------
    op.create_table(
        "posts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("telegram_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_text", sa.Text(), nullable=False),
        sa.Column("cleaned_text", sa.Text(), nullable=True),
        sa.Column("post_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("is_deleted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("telegram_id"),
    )

    # ------------------------------------------------------------------
    # locations
    # ------------------------------------------------------------------
    op.create_table(
        "locations",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("post_id", sa.Integer(), nullable=False),
        sa.Column(
            "geometry",
            geoalchemy2.types.Geometry(geometry_type="POINT", srid=4326),
            nullable=False,
        ),
        sa.Column("geo_type", sa.String(20), nullable=False),
        sa.Column("address", sa.Text(), nullable=False),
        sa.Column("street_name", sa.String(255), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("out_of_bounds", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("resolved_by", sa.String(10), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_locations_geometry",
        "locations",
        ["geometry"],
        postgresql_using="gist",
    )
    op.create_index("ix_locations_confidence", "locations", ["confidence"])

    # ------------------------------------------------------------------
    # slang_dictionary
    # ------------------------------------------------------------------
    op.create_table(
        "slang_dictionary",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("slang", sa.String(255), nullable=False),
        sa.Column("resolved_name", sa.String(255), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("usage_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_learned", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # street_renames
    # ------------------------------------------------------------------
    op.create_table(
        "street_renames",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("old_name_uk", sa.String(255), nullable=False),
        sa.Column("old_name_ru", sa.String(255), nullable=True),
        sa.Column("new_name_uk", sa.String(255), nullable=False),
        sa.Column("new_name_ru", sa.String(255), nullable=True),
        sa.Column("year_renamed", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # channel_state
    # ------------------------------------------------------------------
    op.create_table(
        "channel_state",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("channel_id", sa.BigInteger(), nullable=False),
        sa.Column("channel_link", sa.String(255), nullable=True),
        sa.Column("channel_title", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("last_message_id", sa.BigInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # geocode_cache
    # ------------------------------------------------------------------
    op.create_table(
        "geocode_cache",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("query", sa.String(500), nullable=False),
        sa.Column("result_lat", sa.Float(), nullable=False),
        sa.Column("result_lng", sa.Float(), nullable=False),
        sa.Column("result_type", sa.String(50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("city_id", "query", name="uq_geocode_cache_city_query"),
    )
    op.create_index("ix_geocode_cache_expires_at", "geocode_cache", ["expires_at"])

    # ------------------------------------------------------------------
    # districts
    # ------------------------------------------------------------------
    op.create_table(
        "districts",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("name_ru", sa.String(100), nullable=False),
        sa.Column(
            "polygon",
            geoalchemy2.types.Geometry(geometry_type="POLYGON", srid=4326),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_districts_polygon",
        "districts",
        ["polygon"],
        postgresql_using="gist",
    )

    # ------------------------------------------------------------------
    # unrecognized_tokens
    # ------------------------------------------------------------------
    op.create_table(
        "unrecognized_tokens",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("city_id", sa.Integer(), nullable=False),
        sa.Column("token", sa.String(255), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "sample_post_ids",
            postgresql.ARRAY(sa.BigInteger()),
            nullable=True,
        ),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["city_id"], ["cities.id"]),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # worker_heartbeat  (no city FK — singleton monitor table)
    # ------------------------------------------------------------------
    op.create_table(
        "worker_heartbeat",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "heartbeat_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("status", sa.String(20), nullable=False, server_default="idle"),
        sa.Column("current_job", sa.String(255), nullable=True),
        sa.Column("posts_processed", sa.Integer(), nullable=False, server_default="0"),
        sa.PrimaryKeyConstraint("id"),
    )

    # ------------------------------------------------------------------
    # Odesa seed — idempotent via ON CONFLICT on unique city name
    # ------------------------------------------------------------------
    op.execute(
        sa.text(
            """
            INSERT INTO cities
                (name, name_ru, bbox_north, bbox_south, bbox_east, bbox_west, default_zoom)
            VALUES
                (:name, :name_ru, :bbox_north, :bbox_south, :bbox_east, :bbox_west, :default_zoom)
            ON CONFLICT (name) DO NOTHING
            """
        ).bindparams(
            name="Одеса",
            name_ru="Одесса",
            bbox_north=46.55,
            bbox_south=46.35,
            bbox_east=30.85,
            bbox_west=30.60,
            default_zoom=13,
        )
    )


def downgrade() -> None:
    # Drop tables in reverse FK dependency order
    # worker_heartbeat has no FKs — drop it first among the independents
    op.drop_table("worker_heartbeat")

    # Tables that depend only on cities (order within this group is arbitrary)
    op.drop_index("ix_districts_polygon", table_name="districts")
    op.drop_table("districts")
    op.drop_index("ix_geocode_cache_expires_at", table_name="geocode_cache")
    op.drop_table("geocode_cache")
    op.drop_table("channel_state")
    op.drop_table("street_renames")
    op.drop_table("slang_dictionary")
    op.drop_table("unrecognized_tokens")

    # locations depends on posts; posts depends on cities
    op.drop_index("ix_locations_confidence", table_name="locations")
    op.drop_index("ix_locations_geometry", table_name="locations")
    op.drop_table("locations")
    op.drop_table("posts")

    # cities last — all dependents are gone
    op.drop_table("cities")
