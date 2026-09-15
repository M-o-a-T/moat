"""Add the moat.db.src source-package tracking tables

Revision ID: 281c516acf3a
Revises: 9a3f1c7e4b2d
Create Date: 2026-09-15 00:00:00.000000+00:00

"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "281c516acf3a"
down_revision: str | None = "9a3f1c7e4b2d"
branch_labels: str | (Sequence[str] | None) = None
depends_on: str | (Sequence[str] | None) = None


def upgrade() -> None:
    """Create the five ``src_*`` tables and their constraints.

    Order matters for the foreign keys: roots (``src_spkg``) and the two
    role registries come first, then the per-SPKG dependents
    (``src_archive``, ``src_branch``) that reference them.
    """
    # Anchor: a named source package.
    op.create_table(
        "src_spkg",
        sa.Column("name", sa.String(length=60), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column(
            "prefix",
            sa.String(length=20),
            nullable=True,
            comment="Token for Beads issue targeting",
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    # Registry: archive roles (upstream / mirror / fork / local / …).
    op.create_table(
        "src_archive_role",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column(
            "rank", sa.Integer(), nullable=True, comment="Display order, lower=earlier"
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    # Registry: branch roles (main / release / develop / feature / …).
    op.create_table(
        "src_branch_role",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column(
            "abstract",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="True ⇒ not a long-lived role",
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    # Per-SPKG: one known archive (git remote).
    op.create_table(
        "src_archive",
        sa.Column("spkg_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=False),
        sa.Column(
            "name",
            sa.String(length=40),
            nullable=False,
            comment="Label: github/codeberg/…",
        ),
        sa.Column("url", sa.String(length=200), nullable=False),
        sa.Column(
            "ext_url",
            sa.String(length=200),
            nullable=True,
            comment="Human-facing web URL",
        ),
        sa.Column(
            "api",
            sa.String(length=40),
            nullable=True,
            comment="github|forgejo|radicle|localgit",
        ),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column(
            "default",
            sa.Boolean(),
            nullable=False,
            server_default="0",
            comment="≤1 TRUE per spkg (enforced in code)",
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["src_archive_role.id"], name="fk_archive_role"),
        sa.ForeignKeyConstraint(
            ["spkg_id"], ["src_spkg.id"], name="fk_archive_spkg", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("spkg_id", "name", name="uq_archive_spkg_name"),
    )
    # Per-SPKG: one local branch with free-text status.
    op.create_table(
        "src_branch",
        sa.Column("spkg_id", sa.Integer(), nullable=False),
        sa.Column("role_id", sa.Integer(), nullable=True),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("status", sa.Text(), nullable=True),
        sa.Column(
            "commit",
            sa.String(length=64),
            nullable=True,
            comment="Pinned sha (40/64 chars)",
        ),
        sa.Column(
            "updated",
            sa.DateTime(),
            nullable=True,
            comment="Stamped on status/commit change",
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["role_id"], ["src_branch_role.id"], name="fk_branch_role"),
        sa.ForeignKeyConstraint(
            ["spkg_id"], ["src_spkg.id"], name="fk_branch_spkg", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("spkg_id", "name", name="uq_branch_spkg_name"),
    )


def downgrade() -> None:
    """Drop the five ``src_*`` tables (dependents before roots)."""
    op.drop_table("src_branch")
    op.drop_table("src_archive")
    op.drop_table("src_branch_role")
    op.drop_table("src_archive_role")
    op.drop_table("src_spkg")
