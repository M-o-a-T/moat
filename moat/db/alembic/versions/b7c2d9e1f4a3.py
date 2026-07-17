"""Add the moat.db.inv inventory tables

Revision ID: b7c2d9e1f4a3
Revises: 9a3f1c7e4b2d
Create Date: 2026-07-17 00:00:00.000000+00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "b7c2d9e1f4a3"
down_revision: str | None = "9a3f1c7e4b2d"
branch_labels: str | (Sequence[str] | None) = None
depends_on: str | (Sequence[str] | None) = None


def upgrade() -> None:
    """Create the 8 ``inv_*`` tables, indexes, and seed ThingTyps."""

    # --- vlan ---
    op.create_table(
        "inv_vlan",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("tag", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("desc", sa.String(length=200), nullable=True),
        sa.Column("wlan", sa.String(length=64), nullable=True),
        sa.Column("passwd", sa.String(length=128), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("tag"),
        sa.UniqueConstraint("name"),
    )

    # --- network ---
    op.create_table(
        "inv_network",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("vlan_id", sa.Integer(), nullable=False),
        sa.Column("addr", sa.LargeBinary(length=16), nullable=False),
        sa.Column("prefix", sa.SmallInteger(), nullable=False),
        sa.Column("shift", sa.Integer(), nullable=True),
        sa.Column("desc", sa.String(length=200), nullable=True),
        sa.Column("virt", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("dhcp_first", sa.Integer(), nullable=True),
        sa.Column("dhcp_count", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["vlan_id"], ["inv_vlan.id"], name="fk_network_vlan", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # --- host ---
    op.create_table(
        "inv_host",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("thing_id", sa.Integer(), nullable=False),
        sa.Column("domain", sa.String(length=255), nullable=False),
        sa.Column("loc", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["thing_id"], ["thing.id"], name="fk_host_thing"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("thing_id"),
        sa.UniqueConstraint("domain"),
    )

    # --- interface ---
    op.create_table(
        "inv_interface",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("host_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("vlan_id", sa.Integer(), nullable=True),
        sa.Column("mac", sa.LargeBinary(length=6), nullable=True),
        sa.Column("seqnum", sa.Integer(), nullable=True),
        sa.Column("desc", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["host_id"], ["inv_host.id"], name="fk_interface_host", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["vlan_id"], ["inv_vlan.id"], name="fk_interface_vlan"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("host_id", "name", name="uq_interface_host_name"),
        sa.UniqueConstraint("vlan_id", "seqnum", name="uq_interface_vlan_seqnum"),
    )

    # --- address ---
    op.create_table(
        "inv_address",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("interface_id", sa.Integer(), nullable=False),
        sa.Column("addr", sa.LargeBinary(length=16), nullable=False),
        sa.Column("prefix", sa.SmallInteger(), nullable=True),
        sa.ForeignKeyConstraint(["interface_id"], ["inv_interface.id"], name="fk_address_interface", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("addr"),
    )

    # --- cable ---
    op.create_table(
        "inv_cable",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("iface_a_id", sa.Integer(), nullable=False),
        sa.Column("iface_b_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["iface_a_id"], ["inv_interface.id"], name="fk_cable_iface_a", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["iface_b_id"], ["inv_interface.id"], name="fk_cable_iface_b", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.CheckConstraint("iface_a_id <> iface_b_id", name="ck_cable_distinct"),
        sa.UniqueConstraint("iface_a_id", name="uq_cable_a"),
        sa.UniqueConstraint("iface_b_id", name="uq_cable_b"),
    )

    # --- group ---
    op.create_table(
        "inv_group",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("desc", sa.String(length=200), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # --- host_group (association) ---
    op.create_table(
        "inv_host_group",
        sa.Column("host_id", sa.Integer(), nullable=False),
        sa.Column("group_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["host_id"], ["inv_host.id"], name="fk_host_group_host"),
        sa.ForeignKeyConstraint(["group_id"], ["inv_group.id"], name="fk_host_group_group"),
        sa.PrimaryKeyConstraint("host_id", "group_id"),
    )

    # --- Seed ThingTyps: 'host' and 'wire' ---
    # These are non-abstract thing types for hosts and wires.
    thingtyp = sa.table(
        "thingtyp",
        sa.column("name", sa.String),
        sa.column("abstract", sa.Boolean),
    )
    op.bulk_insert(thingtyp, [
        {"name": "host", "abstract": False},
        {"name": "wire", "abstract": False},
    ])


def downgrade() -> None:
    """Drop the 8 ``inv_*`` tables and remove seeded ThingTyps."""

    # Remove seeded ThingTyps
    thingtyp = sa.table("thingtyp", sa.column("name", sa.String))
    op.execute(
        sa.delete(thingtyp).where(thingtyp.c.name.in_(["host", "wire"]))
    )

    op.drop_table("inv_host_group")
    op.drop_table("inv_group")
    op.drop_table("inv_cable")
    op.drop_table("inv_address")
    op.drop_table("inv_interface")
    op.drop_table("inv_host")
    op.drop_table("inv_network")
    op.drop_table("inv_vlan")
