from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class StreetRename(Base):
    __tablename__ = "street_renames"

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    old_name_uk: Mapped[str] = mapped_column(String(255))
    old_name_ru: Mapped[str | None] = mapped_column(String(255), nullable=True)
    new_name_uk: Mapped[str] = mapped_column(String(255))
    new_name_ru: Mapped[str | None] = mapped_column(String(255), nullable=True)
    year_renamed: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")
