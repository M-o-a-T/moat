"""SQLAlchemy declarations for the rain irrigation schema."""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import (
    Column,
    ForeignKey,
    SmallInteger,
    String,
    Table,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from moat.db.schema import Base
from moat.lib.path import Path
from moat.util.times import now

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from sqlalchemy.engine.interfaces import Dialect


class PathType(TypeDecorator[Path]):
    """Store a :class:`moat.lib.path.Path` column as ``VARCHAR(200)``.

    Binding serialises with :func:`str`; loading parses with
    :meth:`Path.from_str`. The empty path is ``":""``; a nullable column
    maps to ``None`` ↔ SQL ``NULL``.
    """

    impl = String(200)
    cache_ok = True

    def process_bind_param(self, value: Path | None, dialect: Dialect) -> str | None:  # noqa:ARG002
        """Serialise a :class:`Path` (or ``None``) for the database."""
        if value is None:
            return None
        return str(value)

    def process_result_value(self, value: str | None, dialect: Dialect) -> Path | None:  # noqa:ARG002
        """Parse a stored string (or ``None``) back into a :class:`Path`."""
        if value is None:
            return None
        return Path.from_str(value)


# Association tables (many-to-many). Their foreign keys are string-keyed so
# they may be declared ahead of the mapped classes that reference them via
# ``secondary=``; both sides of each link cascade on delete.
group_valves = Table(
    "rain_group_valves",
    Base.metadata,
    Column(
        "group_id",
        ForeignKey("rain_group.id", name="fk_group_valves_group", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "valve_id",
        ForeignKey("rain_valve.id", name="fk_group_valves_valve", ondelete="CASCADE"),
        primary_key=True,
    ),
)
group_days = Table(
    "rain_group_days",
    Base.metadata,
    Column(
        "group_id",
        ForeignKey("rain_group.id", name="fk_group_days_group", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "dayrange_id",
        ForeignKey("rain_dayrange.id", name="fk_group_days_dayrange", ondelete="CASCADE"),
        primary_key=True,
    ),
)
group_xdays = Table(
    "rain_group_xdays",
    Base.metadata,
    Column(
        "group_id",
        ForeignKey("rain_group.id", name="fk_group_xdays_group", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "dayrange_id",
        ForeignKey("rain_dayrange.id", name="fk_group_xdays_dayrange", ondelete="CASCADE"),
        primary_key=True,
    ),
)
dayrange_days = Table(
    "rain_dayrange_days",
    Base.metadata,
    Column(
        "dayrange_id",
        ForeignKey("rain_dayrange.id", name="fk_dayrange_days_dayrange", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "day_id",
        ForeignKey("rain_day.id", name="fk_dayrange_days_day", ondelete="CASCADE"),
        primary_key=True,
    ),
)


class Site(Base):
    """One irrigated site and its top-level settings."""

    __tablename__ = "rain_site"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, type_=String(200))
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    rate: Mapped[float] = mapped_column(default=10.0, server_default="10")
    rain_delay: Mapped[int] = mapped_column(default=300, server_default="300")

    envgroups: Mapped[set[EnvGroup]] = relationship(
        "EnvGroup", back_populates="site", passive_deletes=True
    )
    sensors: Mapped[set[Sensor]] = relationship(
        "Sensor", back_populates="site", passive_deletes=True
    )
    feeds: Mapped[set[Feed]] = relationship("Feed", back_populates="site", passive_deletes=True)
    controllers: Mapped[set[Controller]] = relationship(
        "Controller", back_populates="site", passive_deletes=True
    )
    groups: Mapped[set[Group]] = relationship("Group", back_populates="site", passive_deletes=True)
    histories: Mapped[set[History]] = relationship(
        "History", back_populates="site", passive_deletes=True
    )
    logs: Mapped[set[Log]] = relationship("Log", back_populates="site", passive_deletes=True)

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
    ranges: Mapped[set[DayRange]] = relationship(
        "DayRange", secondary=dayrange_days, back_populates="days", passive_deletes=True
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
    valves: Mapped[set[Valve]] = relationship(
        "Valve", back_populates="envgroup", passive_deletes=True
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
    state: Mapped[Path] = mapped_column(type_=PathType(), unique=True)
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
    flow_monitor: Mapped[Path | None] = mapped_column(type_=PathType(), nullable=True, unique=True)
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    flow: Mapped[float | None] = mapped_column(nullable=True, default=10.0, server_default="10")
    max_flow_wait: Mapped[int] = mapped_column(default=300, server_default="300")
    disabled: Mapped[bool] = mapped_column(default=False, server_default="0")
    site_id: Mapped[int] = mapped_column(
        ForeignKey("rain_site.id", name="fk_feed_site", ondelete="CASCADE"),
    )

    site: Mapped[Site] = relationship("Site", back_populates="feeds")
    valves: Mapped[set[Valve]] = relationship("Valve", back_populates="feed", passive_deletes=True)

    @property
    def max_flow_wait_td(self) -> timedelta:
        """``max_flow_wait`` as a :class:`~datetime.timedelta`."""
        return timedelta(seconds=self.max_flow_wait)


class Controller(Base):
    """A device (Wago or similar) that drives valves."""

    __tablename__ = "rain_controller"
    __table_args__ = (UniqueConstraint("site_id", "name", name="uq_controller_site_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(type_=String(200))
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    location: Mapped[str] = mapped_column(type_=String(200))
    max_on: Mapped[int] = mapped_column(default=3, server_default="3")
    site_id: Mapped[int] = mapped_column(
        ForeignKey("rain_site.id", name="fk_controller_site", ondelete="CASCADE"),
    )

    site: Mapped[Site] = relationship("Site", back_populates="controllers")
    valves: Mapped[set[Valve]] = relationship(
        "Valve", back_populates="controller", passive_deletes=True
    )
    logs: Mapped[set[Log]] = relationship("Log", back_populates="controller", passive_deletes=True)


class Valve(Base):
    """One controllable outlet of water on a :class:`Controller`."""

    __tablename__ = "rain_valve"
    __table_args__ = (UniqueConstraint("controller_id", "name", name="uq_valve_controller_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(type_=String(200))
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    location: Mapped[str] = mapped_column(type_=String(200))
    command: Mapped[Path | None] = mapped_column(type_=PathType(), nullable=True, unique=True)
    state: Mapped[Path | None] = mapped_column(type_=PathType(), nullable=True, unique=True)
    verbose: Mapped[int] = mapped_column(type_=SmallInteger, default=0, server_default="0")
    flow: Mapped[float] = mapped_column()
    area: Mapped[float] = mapped_column()
    max_level: Mapped[float] = mapped_column(default=10.0, server_default="10")
    start_level: Mapped[float] = mapped_column(default=8.0, server_default="8")
    stop_level: Mapped[float] = mapped_column(default=3.0, server_default="3")
    shade: Mapped[float] = mapped_column(default=1.0, server_default="1")
    max_run: Mapped[int | None] = mapped_column(nullable=True)
    min_delay: Mapped[int | None] = mapped_column(nullable=True)
    runoff: Mapped[float] = mapped_column(default=1.0, server_default="1")
    time: Mapped[datetime] = mapped_column(index=True, default=now)
    level: Mapped[float] = mapped_column(default=0.0, server_default="0")
    priority: Mapped[bool] = mapped_column(default=False, server_default="0")
    feed_id: Mapped[int] = mapped_column(
        ForeignKey("rain_feed.id", name="fk_valve_feed", ondelete="CASCADE"),
    )
    controller_id: Mapped[int] = mapped_column(
        ForeignKey("rain_controller.id", name="fk_valve_controller", ondelete="CASCADE"),
    )
    envgroup_id: Mapped[int] = mapped_column(
        ForeignKey("rain_envgroup.id", name="fk_valve_envgroup", ondelete="CASCADE"),
    )

    feed: Mapped[Feed] = relationship("Feed", back_populates="valves")
    controller: Mapped[Controller] = relationship("Controller", back_populates="valves")
    envgroup: Mapped[EnvGroup] = relationship("EnvGroup", back_populates="valves")
    groups: Mapped[set[Group]] = relationship(
        "Group", secondary=group_valves, back_populates="valves", passive_deletes=True
    )
    schedules: Mapped[set[Schedule]] = relationship(
        "Schedule", back_populates="valve", passive_deletes=True
    )
    overrides: Mapped[set[ValveOverride]] = relationship(
        "ValveOverride", back_populates="valve", passive_deletes=True
    )
    levels: Mapped[set[Level]] = relationship(
        "Level", back_populates="valve", passive_deletes=True
    )
    logs: Mapped[set[Log]] = relationship("Log", back_populates="valve", passive_deletes=True)

    @property
    def max_run_td(self) -> timedelta | None:
        """``max_run`` as a :class:`~datetime.timedelta`, or ``None``."""
        return None if self.max_run is None else timedelta(seconds=self.max_run)

    @property
    def min_delay_td(self) -> timedelta | None:
        """``min_delay`` as a :class:`~datetime.timedelta`, or ``None``."""
        return None if self.min_delay is None else timedelta(seconds=self.min_delay)


class DayRange(Base):
    """An intersection of :class:`Day` unions, used by a :class:`Group`."""

    __tablename__ = "rain_dayrange"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, type_=String(30))
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)

    days: Mapped[set[Day]] = relationship(
        "Day", secondary=dayrange_days, back_populates="ranges", passive_deletes=True
    )
    groups: Mapped[set[Group]] = relationship(
        "Group", secondary=group_days, back_populates="days", passive_deletes=True
    )
    xgroups: Mapped[set[Group]] = relationship(
        "Group", secondary=group_xdays, back_populates="xdays", passive_deletes=True
    )


class Group(Base):
    """A named bundle of valves sharing a schedule window."""

    __tablename__ = "rain_group"
    __table_args__ = (UniqueConstraint("site_id", "name", name="uq_group_site_name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(type_=String(200))
    comment: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    adj: Mapped[float | None] = mapped_column(nullable=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("rain_site.id", name="fk_group_site", ondelete="CASCADE"),
    )

    site: Mapped[Site] = relationship("Site", back_populates="groups")
    days: Mapped[set[DayRange]] = relationship(
        "DayRange", secondary=group_days, back_populates="groups", passive_deletes=True
    )
    xdays: Mapped[set[DayRange]] = relationship(
        "DayRange", secondary=group_xdays, back_populates="xgroups", passive_deletes=True
    )
    valves: Mapped[set[Valve]] = relationship(
        "Valve", secondary=group_valves, back_populates="groups", passive_deletes=True
    )
    overrides: Mapped[set[GroupOverride]] = relationship(
        "GroupOverride", back_populates="group", passive_deletes=True
    )
    adjusters: Mapped[set[GroupAdjust]] = relationship(
        "GroupAdjust", back_populates="group", passive_deletes=True
    )


class GroupOverride(Base):
    """A window that allows or blocks a :class:`Group`'s schedule."""

    __tablename__ = "rain_group_override"
    __table_args__ = (UniqueConstraint("group_id", "start", name="uq_groupoverride_group_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    allowed: Mapped[bool] = mapped_column(default=False, server_default="0")
    start: Mapped[datetime] = mapped_column(index=True)
    duration: Mapped[int] = mapped_column()
    on_level: Mapped[float | None] = mapped_column(nullable=True)
    off_level: Mapped[float | None] = mapped_column(nullable=True)
    group_id: Mapped[int] = mapped_column(
        ForeignKey("rain_group.id", name="fk_groupoverride_group", ondelete="CASCADE"),
    )

    group: Mapped[Group] = relationship("Group", back_populates="overrides")

    @property
    def duration_td(self) -> timedelta:
        """``duration`` as a :class:`~datetime.timedelta`."""
        return timedelta(seconds=self.duration)

    @property
    def end(self) -> datetime:
        """Moment this override ends."""
        return self.start + self.duration_td


class ValveOverride(Base):
    """A window that forces a :class:`Valve` on or off."""

    __tablename__ = "rain_valve_override"
    __table_args__ = (UniqueConstraint("valve_id", "start", name="uq_valveoverride_valve_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str | None] = mapped_column(type_=String(200), nullable=True)
    running: Mapped[bool] = mapped_column(default=False, server_default="0")
    start: Mapped[datetime] = mapped_column(index=True)
    duration: Mapped[int] = mapped_column()
    on_level: Mapped[float | None] = mapped_column(nullable=True)
    off_level: Mapped[float | None] = mapped_column(nullable=True)
    valve_id: Mapped[int] = mapped_column(
        ForeignKey("rain_valve.id", name="fk_valveoverride_valve", ondelete="CASCADE"),
    )

    valve: Mapped[Valve] = relationship("Valve", back_populates="overrides")

    @property
    def duration_td(self) -> timedelta:
        """``duration`` as a :class:`~datetime.timedelta`."""
        return timedelta(seconds=self.duration)

    @property
    def end(self) -> datetime:
        """Moment this override ends."""
        return self.start + self.duration_td


class GroupAdjust(Base):
    """A dated multiplier interpolating a :class:`Group`'s water demand."""

    __tablename__ = "rain_group_adjust"
    __table_args__ = (UniqueConstraint("group_id", "start", name="uq_groupadjust_group_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    start: Mapped[datetime] = mapped_column(index=True)
    factor: Mapped[float] = mapped_column()
    group_id: Mapped[int] = mapped_column(
        ForeignKey("rain_group.id", name="fk_groupadjust_group", ondelete="CASCADE"),
    )

    group: Mapped[Group] = relationship("Group", back_populates="adjusters")


class Schedule(Base):
    """One planned run of a :class:`Valve`."""

    __tablename__ = "rain_schedule"
    __table_args__ = (UniqueConstraint("valve_id", "start", name="uq_schedule_valve_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    start: Mapped[datetime] = mapped_column(index=True)
    duration: Mapped[int] = mapped_column()
    seen: Mapped[bool] = mapped_column(default=False, server_default="0")
    changed: Mapped[bool] = mapped_column(default=False, server_default="0")
    forced: Mapped[bool] = mapped_column(default=False, server_default="0")
    valve_id: Mapped[int] = mapped_column(
        ForeignKey("rain_valve.id", name="fk_schedule_valve", ondelete="CASCADE"),
    )

    valve: Mapped[Valve] = relationship("Valve", back_populates="schedules")

    @property
    def duration_td(self) -> timedelta:
        """``duration`` as a :class:`~datetime.timedelta`."""
        return timedelta(seconds=self.duration)

    @property
    def end(self) -> datetime:
        """Moment this run ends."""
        return self.start + self.duration_td


class Level(Base):
    """A historic water-capacity sample for a :class:`Valve`."""

    __tablename__ = "rain_level"
    __table_args__ = (UniqueConstraint("valve_id", "time", name="uq_level_valve_time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    time: Mapped[datetime] = mapped_column(index=True)
    level: Mapped[float] = mapped_column()
    flow: Mapped[float] = mapped_column(default=0.0, server_default="0")
    forced: Mapped[bool] = mapped_column(default=False, server_default="0")
    valve_id: Mapped[int] = mapped_column(
        ForeignKey("rain_valve.id", name="fk_level_valve", ondelete="CASCADE"),
    )

    valve: Mapped[Valve] = relationship("Valve", back_populates="levels")


class History(Base):
    """Accumulated weather and feed measurements for a :class:`Site`."""

    __tablename__ = "rain_history"
    __table_args__ = (UniqueConstraint("site_id", "time", name="uq_history_site_time"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    time: Mapped[datetime] = mapped_column(index=True)
    rain: Mapped[float] = mapped_column(default=0.0, server_default="0")
    feed: Mapped[float] = mapped_column(default=0.0, server_default="0")
    temp: Mapped[float | None] = mapped_column(nullable=True)
    wind: Mapped[float | None] = mapped_column(nullable=True)
    sun: Mapped[float | None] = mapped_column(nullable=True)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("rain_site.id", name="fk_history_site", ondelete="CASCADE"),
    )

    site: Mapped[Site] = relationship("Site", back_populates="histories")


class Log(Base):
    """A scheduler or operator event for a :class:`Site`."""

    __tablename__ = "rain_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    logger: Mapped[str] = mapped_column(type_=String(200))
    timestamp: Mapped[datetime] = mapped_column(index=True, default=now)
    text: Mapped[str] = mapped_column(type_=Text)
    site_id: Mapped[int] = mapped_column(
        ForeignKey("rain_site.id", name="fk_log_site", ondelete="CASCADE"),
    )
    controller_id: Mapped[int | None] = mapped_column(
        ForeignKey("rain_controller.id", name="fk_log_controller", ondelete="CASCADE"),
        nullable=True,
    )
    valve_id: Mapped[int | None] = mapped_column(
        ForeignKey("rain_valve.id", name="fk_log_valve", ondelete="CASCADE"),
        nullable=True,
    )

    site: Mapped[Site] = relationship("Site", back_populates="logs")
    controller: Mapped[Controller | None] = relationship("Controller", back_populates="logs")
    valve: Mapped[Valve | None] = relationship("Valve", back_populates="logs")
