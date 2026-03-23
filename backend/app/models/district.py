from __future__ import annotations

from geoalchemy2 import Geometry
from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class District(Base):
    __tablename__ = "districts"

    id: Mapped[int] = mapped_column(primary_key=True)
    city_id: Mapped[int] = mapped_column(ForeignKey("cities.id"))
    name: Mapped[str] = mapped_column(String(100))
    name_ru: Mapped[str] = mapped_column(String(100))
    polygon: Mapped[str] = mapped_column(Geometry("POLYGON", srid=4326))

    __table_args__ = (Index("ix_districts_polygon", "polygon", postgresql_using="gist"),)
