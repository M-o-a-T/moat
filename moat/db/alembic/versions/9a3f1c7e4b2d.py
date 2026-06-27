"""Add the moat.db.rain irrigation tables

Revision ID: 9a3f1c7e4b2d
Revises: dd1007d00e262b5c
Create Date: 2026-06-27 00:00:00.000000+00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "9a3f1c7e4b2d"
down_revision: str | None = "dd1007d00e262b5c"
branch_labels: str | (Sequence[str] | None) = None
depends_on: str | (Sequence[str] | None) = None


def upgrade() -> None:
    """Create the 22 ``rain_*`` tables and their indexes."""
    # Roots: Day, DayRange, Site (no foreign keys).
    op.create_table(
        "rain_day",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "rain_dayrange",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=30), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "rain_site",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column("rate", sa.Float(), nullable=False, server_default="10"),
        sa.Column("rain_delay", sa.Integer(), nullable=False, server_default="300"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # Children of Site (single FK).
    op.create_table(
        "rain_controller",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=False),
        sa.Column("max_on", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_id"], ["rain_site.id"], name="fk_controller_site", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "name", name="uq_controller_site_name"),
    )
    op.create_table(
        "rain_envgroup",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column("factor", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("rain", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_id"], ["rain_site.id"], name="fk_envgroup_site", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "name", name="uq_envgroup_site_name"),
    )
    op.create_table(
        "rain_feed",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("flow_monitor", sa.String(length=200), nullable=True),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column("flow", sa.Float(), nullable=True, server_default="10"),
        sa.Column("max_flow_wait", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("disabled", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_id"], ["rain_site.id"], name="fk_feed_site", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("flow_monitor"),
        sa.UniqueConstraint("site_id", "name", name="uq_feed_site_name"),
    )
    op.create_table(
        "rain_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column("adj", sa.Float(), nullable=True),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_id"], ["rain_site.id"], name="fk_group_site", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "name", name="uq_group_site_name"),
    )
    op.create_table(
        "rain_history",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("time", sa.DateTime(), nullable=False),
        sa.Column("rain", sa.Float(), nullable=False, server_default="0"),
        sa.Column("feed", sa.Float(), nullable=False, server_default="0"),
        sa.Column("temp", sa.Float(), nullable=True),
        sa.Column("wind", sa.Float(), nullable=True),
        sa.Column("sun", sa.Float(), nullable=True),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_id"], ["rain_site.id"], name="fk_history_site", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("site_id", "time", name="uq_history_site_time"),
    )
    op.create_table(
        "rain_sensor",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=8), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("state", sa.String(length=200), nullable=False),
        sa.Column("weight", sa.SmallInteger(), nullable=False, server_default="10"),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["site_id"], ["rain_site.id"], name="fk_sensor_site", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("site_id", "kind", "name", name="uq_sensor_site_kind_name"),
        sa.UniqueConstraint("state"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Children of Day / EnvGroup / Group.
    op.create_table(
        "rain_daytime",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("descr", sa.String(length=200), nullable=False),
        sa.Column("day_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["day_id"], ["rain_day.id"], name="fk_daytime_day", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("day_id", "descr", name="uq_daytime_day_descr"),
    )
    op.create_table(
        "rain_envitem",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("factor", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("temp", sa.Float(), nullable=True),
        sa.Column("wind", sa.Float(), nullable=True),
        sa.Column("sun", sa.Float(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"], ["rain_envgroup.id"], name="fk_envitem_group", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rain_group_adjust",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("start", sa.DateTime(), nullable=False),
        sa.Column("factor", sa.Float(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"], ["rain_group.id"], name="fk_groupadjust_group", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("group_id", "start", name="uq_groupadjust_group_start"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rain_group_override",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("allowed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("start", sa.DateTime(), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("on_level", sa.Float(), nullable=True),
        sa.Column("off_level", sa.Float(), nullable=True),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"], ["rain_group.id"], name="fk_groupoverride_group", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("group_id", "start", name="uq_groupoverride_group_start"),
        sa.PrimaryKeyConstraint("id"),
    )

    # Valve depends on Controller, Feed, EnvGroup.
    op.create_table(
        "rain_valve",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column("location", sa.String(length=200), nullable=False),
        sa.Column("command", sa.String(length=200), nullable=True),
        sa.Column("state", sa.String(length=200), nullable=True),
        sa.Column("verbose", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("flow", sa.Float(), nullable=False),
        sa.Column("area", sa.Float(), nullable=False),
        sa.Column("max_level", sa.Float(), nullable=False, server_default="10"),
        sa.Column("start_level", sa.Float(), nullable=False, server_default="8"),
        sa.Column("stop_level", sa.Float(), nullable=False, server_default="3"),
        sa.Column("shade", sa.Float(), nullable=False, server_default="1"),
        sa.Column("max_run", sa.Integer(), nullable=True),
        sa.Column("min_delay", sa.Integer(), nullable=True),
        sa.Column("runoff", sa.Float(), nullable=False, server_default="1"),
        sa.Column("time", sa.DateTime(), nullable=False),
        sa.Column("level", sa.Float(), nullable=False, server_default="0"),
        sa.Column("priority", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("feed_id", sa.Integer(), nullable=False),
        sa.Column("controller_id", sa.Integer(), nullable=False),
        sa.Column("envgroup_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["controller_id"],
            ["rain_controller.id"],
            name="fk_valve_controller",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["envgroup_id"],
            ["rain_envgroup.id"],
            name="fk_valve_envgroup",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["feed_id"], ["rain_feed.id"], name="fk_valve_feed", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("controller_id", "name", name="uq_valve_controller_name"),
        sa.UniqueConstraint("command"),
        sa.UniqueConstraint("state"),
    )

    # Children of Valve.
    op.create_table(
        "rain_level",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("time", sa.DateTime(), nullable=False),
        sa.Column("level", sa.Float(), nullable=False),
        sa.Column("flow", sa.Float(), nullable=False, server_default="0"),
        sa.Column("forced", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("valve_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["valve_id"], ["rain_valve.id"], name="fk_level_valve", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("valve_id", "time", name="uq_level_valve_time"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rain_schedule",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("start", sa.DateTime(), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("seen", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("changed", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("forced", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("valve_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["valve_id"], ["rain_valve.id"], name="fk_schedule_valve", ondelete="CASCADE"
        ),
        sa.UniqueConstraint("valve_id", "start", name="uq_schedule_valve_start"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "rain_valve_override",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=True),
        sa.Column("running", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("start", sa.DateTime(), nullable=False),
        sa.Column("duration", sa.Integer(), nullable=False),
        sa.Column("on_level", sa.Float(), nullable=True),
        sa.Column("off_level", sa.Float(), nullable=True),
        sa.Column("valve_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["valve_id"], ["rain_valve.id"], name="fk_valveoverride_valve", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("valve_id", "start", name="uq_valveoverride_valve_start"),
    )
    op.create_table(
        "rain_log",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("logger", sa.String(length=200), nullable=False),
        sa.Column("timestamp", sa.DateTime(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("site_id", sa.Integer(), nullable=False),
        sa.Column("controller_id", sa.Integer(), nullable=True),
        sa.Column("valve_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["controller_id"],
            ["rain_controller.id"],
            name="fk_log_controller",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["site_id"], ["rain_site.id"], name="fk_log_site", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["valve_id"], ["rain_valve.id"], name="fk_log_valve", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
    )

    # Many-to-many association tables (composite primary key, both FKs cascade).
    op.create_table(
        "rain_dayrange_days",
        sa.Column("dayrange_id", sa.Integer(), nullable=False),
        sa.Column("day_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["day_id"], ["rain_day.id"], name="fk_dayrange_days_day", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["dayrange_id"],
            ["rain_dayrange.id"],
            name="fk_dayrange_days_dayrange",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("dayrange_id", "day_id"),
    )
    op.create_table(
        "rain_group_days",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("dayrange_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dayrange_id"],
            ["rain_dayrange.id"],
            name="fk_group_days_dayrange",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["rain_group.id"], name="fk_group_days_group", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("group_id", "dayrange_id"),
    )
    op.create_table(
        "rain_group_xdays",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("dayrange_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["dayrange_id"],
            ["rain_dayrange.id"],
            name="fk_group_xdays_dayrange",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["group_id"], ["rain_group.id"], name="fk_group_xdays_group", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("group_id", "dayrange_id"),
    )
    op.create_table(
        "rain_group_valves",
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.Column("valve_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["group_id"], ["rain_group.id"], name="fk_group_valves_group", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["valve_id"], ["rain_valve.id"], name="fk_group_valves_valve", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("group_id", "valve_id"),
    )

    # Non-unique indexes on the timestamp / start columns (model: index=True).
    op.create_index("ix_rain_history_time", "rain_history", ["time"], unique=False)
    op.create_index("ix_rain_group_adjust_start", "rain_group_adjust", ["start"], unique=False)
    op.create_index("ix_rain_group_override_start", "rain_group_override", ["start"], unique=False)
    op.create_index("ix_rain_valve_time", "rain_valve", ["time"], unique=False)
    op.create_index("ix_rain_level_time", "rain_level", ["time"], unique=False)
    op.create_index("ix_rain_log_timestamp", "rain_log", ["timestamp"], unique=False)
    op.create_index("ix_rain_schedule_start", "rain_schedule", ["start"], unique=False)
    op.create_index("ix_rain_valve_override_start", "rain_valve_override", ["start"], unique=False)


def downgrade() -> None:
    """Drop the indexes and ``rain_*`` tables in reverse dependency order."""
    op.drop_index("ix_rain_valve_override_start", table_name="rain_valve_override")
    op.drop_index("ix_rain_schedule_start", table_name="rain_schedule")
    op.drop_index("ix_rain_log_timestamp", table_name="rain_log")
    op.drop_index("ix_rain_level_time", table_name="rain_level")
    op.drop_index("ix_rain_valve_time", table_name="rain_valve")
    op.drop_index("ix_rain_group_override_start", table_name="rain_group_override")
    op.drop_index("ix_rain_group_adjust_start", table_name="rain_group_adjust")
    op.drop_index("ix_rain_history_time", table_name="rain_history")

    op.drop_table("rain_group_valves")
    op.drop_table("rain_group_xdays")
    op.drop_table("rain_group_days")
    op.drop_table("rain_dayrange_days")
    op.drop_table("rain_log")
    op.drop_table("rain_valve_override")
    op.drop_table("rain_schedule")
    op.drop_table("rain_level")
    op.drop_table("rain_valve")
    op.drop_table("rain_group_override")
    op.drop_table("rain_group_adjust")
    op.drop_table("rain_envitem")
    op.drop_table("rain_sensor")
    op.drop_table("rain_history")
    op.drop_table("rain_group")
    op.drop_table("rain_feed")
    op.drop_table("rain_envgroup")
    op.drop_table("rain_daytime")
    op.drop_table("rain_controller")
    op.drop_table("rain_site")
    op.drop_table("rain_dayrange")
    op.drop_table("rain_day")
