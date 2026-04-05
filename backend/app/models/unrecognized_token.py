from __future__ import annotations

from datetime import datetime

from sqlalchemy import ARRAY, BigInteger, DateTime, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class UnrecognizedToken(Base):
    __tablename__ = "unrecognized_tokens"

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    token: Mapped[str] = mapped_column(String(255))
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    sample_post_ids: Mapped[list[int] | None] = mapped_column(ARRAY(BigInteger), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint("city_id", "token", name="uq_unrecognized_tokens_city_token"),)
