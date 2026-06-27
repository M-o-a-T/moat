"""SQLAlchemy declarations for the rain irrigation schema (leaf entities)."""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import ForeignKey, SmallInteger, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from moat.db.schema import Base


class Site(Base):
    """One irrigated site and its top-level settings."""

    __tablename__ = "rain_site"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, type_=String(200))
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    var: Mapped[str | None] = mapped_column(unique=True, type_=String(200), nullable=True)
    rate: Mapped[float] = mapped_column(default=10.0, server_default="10")
    rain_delay: Mapped[int] = mapped_column(default=300, server_default="300")

    envgroups: Mapped[set[EnvGroup]] = relationship(
        "EnvGroup", back_populates="site", passive_deletes=True
    )
    sensors: Mapped[set[Sensor]] = relationship(
        "Sensor", back_populates="site", passive_deletes=True
    )
    feeds: Mapped[set[Feed]] = relationship("Feed", back_populates="site", passive_deletes=True)

    @property
    def rain_delay_td(self) -> timedelta:
        """``rain_delay`` as a :class:`~datetime.timedelta`."""
        return timedelta(seconds=self.rain_delay)


class Day(Base):
    """A named union of day-times."""

    __tablename__ = "rain_day"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, type_=String(30))

    times: Mapped[set[DayTime]] = relationship(
        "DayTime", back_populates="day", passive_deletes=True
    )


class DayTime(Base):
    """One time-description fragment belonging to a :class:`Day`."""

    __tablename__ = "rain_daytime"
    __table_args__ = (UniqueConstraint("day_id", "descr", name="uq_daytime_day_descr"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    descr: Mapped[str] = mapped_column(type_=String(200))
    day_id: Mapped[int] = mapped_column(
        ForeignKey("rain_day.id", name="fk_daytime_day", ondelete="CASCADE"),
    )

    day: Mapped[Day] = relationship("Day", back_populates="times")


class EnvGroup(Base):
    """A named group of environmental factors for a :class:`Site`."""

    __tablename__ = "rain_envgroup"
    __table_args__ = (UniqueConstraint("site_id", "name", name="uq_envgroup_site_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(type_=String(200))
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    factor: Mapped[float] = mapped_column(default=1.0, server_default="1.0")
    rain: Mapped[bool] = mapped_column(default=True, server_default="1")
    site_id: Mapped[int] = mapped_column(
        ForeignKey("rain_site.id", name="fk_envgroup_site", ondelete="CASCADE"),
    )

    site: Mapped[Site] = relationship("Site", back_populates="envgroups")
    items: Mapped[set[EnvItem]] = relationship(
        "EnvItem", back_populates="group", passive_deletes=True
    )


class EnvItem(Base):
    """One data point in an :class:`EnvGroup`."""

    __tablename__ = "rain_envitem"

    id: Mapped[int] = mapped_column(primary_key=True)
    factor: Mapped[float] = mapped_column(default=1.0, server_default="1.0")
    temp: Mapped[float | None] = mapped_column(nullable=True)
    wind: Mapped[float | None] = mapped_column(nullable=True)
    sun: Mapped[float | None] = mapped_column(nullable=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("rain_envgroup.id", name="fk_envitem_group", ondelete="CASCADE"),
    )

    group: Mapped[EnvGroup] = relationship("EnvGroup", back_populates="items")


class Sensor(Base):
    """A weather sensor of a given kind attached to a :class:`Site`."""

    __tablename__ = "rain_sensor"
    __table_args__ = (
        UniqueConstraint("site_id", "kind", "name", name="uq_sensor_site_kind_name"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    kind: Mapped[str] = mapped_column(type_=String(8), comment="rain|temp|wind|sun")
    name: Mapped[str] = mapped_column(type_=String(200))
    var: Mapped[str] = mapped_column(unique=True, type_=String(200))
    weight: Mapped[int] = mapped_column(type_=SmallInteger, default=10, server_default="10")
    site_id: Mapped[int] = mapped_column(
        ForeignKey("rain_site.id", name="fk_sensor_site", ondelete="CASCADE"),
    )

    site: Mapped[Site] = relationship("Site", back_populates="sensors")


class Feed(Base):
    """A source of water for a :class:`Site`."""

    __tablename__ = "rain_feed"
    __table_args__ = (UniqueConstraint("site_id", "name", name="uq_feed_site_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(type_=String(200))
    var: Mapped[str | None] = mapped_column(unique=True, type_=String(200), nullable=True)
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    flow: Mapped[float | None] = mapped_column(nullable=True, default=10.0, server_default="10")
    max_flow_wait: Mapped[int] = mapped_column(default=300, server_default="300")
    disabled: Mapped[bool] = mapped_column(default=False, server_default="0")
    site_id: Mapped[int] = mapped_column(
        ForeignKey("rain_site.id", name="fk_feed_site", ondelete="CASCADE"),
    )

    site: Mapped[Site] = relationship("Site", back_populates="feeds")

    @property
    def max_flow_wait_td(self) -> timedelta:
        """``max_flow_wait`` as a :class:`~datetime.timedelta`."""
        return timedelta(seconds=self.max_flow_wait)
