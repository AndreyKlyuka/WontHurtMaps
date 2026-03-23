from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class WorkerHeartbeat(Base):
    __tablename__ = "worker_heartbeat"

    id: Mapped[int] = mapped_column(primary_key=True)
    heartbeat_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    status: Mapped[str] = mapped_column(String(20), default="idle")
    current_job: Mapped[str | None] = mapped_column(String(255), nullable=True)
    posts_processed: Mapped[int] = mapped_column(Integer, default=0)
