from __future__ import annotations

from datetime import datetime

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class ChannelState(Base):
    __tablename__ = "channel_state"

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    channel_id: Mapped[int] = mapped_column(BigInteger)
    channel_link: Mapped[str | None] = mapped_column(String(255), nullable=True)
    channel_title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    last_message_id: Mapped[int] = mapped_column(BigInteger, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
