from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class GeocodeCache(Base):
    __tablename__ = "geocode_cache"

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    query: Mapped[str] = mapped_column(String(500))
    result_lat: Mapped[float] = mapped_column(Float)
    result_lng: Mapped[float] = mapped_column(Float)
    result_type: Mapped[str] = mapped_column(String(50))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    hit_count: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("city_id", "query", name="uq_geocode_cache_city_query"),
        Index("ix_geocode_cache_expires_at", "expires_at"),
    )
