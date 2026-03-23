from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class SlangDictionary(Base):
    __tablename__ = "slang_dictionary"

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    slang: Mapped[str] = mapped_column(String(255))
    resolved_name: Mapped[str] = mapped_column(String(255))
    entity_type: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20), default="pending")
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    auto_learned: Mapped[bool] = mapped_column(Boolean, default=True)
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
