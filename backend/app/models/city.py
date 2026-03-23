from __future__ import annotations

from sqlalchemy import Float, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class City(Base):
    __tablename__ = "cities"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100), unique=True)
    name_ru: Mapped[str] = mapped_column(String(100))
    bbox_north: Mapped[float] = mapped_column(Float)
    bbox_south: Mapped[float] = mapped_column(Float)
    bbox_east: Mapped[float] = mapped_column(Float)
    bbox_west: Mapped[float] = mapped_column(Float)
    default_zoom: Mapped[int] = mapped_column(Integer, default=13)
