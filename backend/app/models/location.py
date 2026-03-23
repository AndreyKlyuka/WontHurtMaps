from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from geoalchemy2 import Geometry
from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.post import Post


class Location(Base):
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(primary_key=True)
    post_id: Mapped[int] = mapped_column(ForeignKey("posts.id"))
    geometry: Mapped[str] = mapped_column(Geometry("POINT", srid=4326))
    geo_type: Mapped[str] = mapped_column(String(20))
    address: Mapped[str] = mapped_column(Text)
    street_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    confidence: Mapped[float] = mapped_column(Float)
    out_of_bounds: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved: Mapped[bool] = mapped_column(Boolean, default=False)
    resolved_by: Mapped[str | None] = mapped_column(String(10), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    post: Mapped[Post] = relationship(back_populates="locations")

    __table_args__ = (
        Index("ix_locations_geometry", "geometry", postgresql_using="gist"),
        Index("ix_locations_confidence", "confidence"),
    )
