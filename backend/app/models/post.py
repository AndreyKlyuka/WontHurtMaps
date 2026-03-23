from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.location import Location


class Post(Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True)
    telegram_id: Mapped[int] = mapped_column(BigInteger, unique=True)
    channel_id: Mapped[int] = mapped_column(BigInteger)
    raw_text: Mapped[str] = mapped_column(Text)
    cleaned_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    post_date: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="pending")
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))

    locations: Mapped[list[Location]] = relationship(back_populates="post")
