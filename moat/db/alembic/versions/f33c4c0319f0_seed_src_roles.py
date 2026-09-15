"""Seed the moat.db.src default role vocabularies

Revision ID: f33c4c0319f0
Revises: 281c516acf3a
Create Date: 2026-09-15 00:00:01.000000+00:00

"""

from __future__ import annotations

import logging
from pathlib import Path

import sqlalchemy as sa
from alembic import op

from moat.util import yload

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger("alembic.migration.moat.db.src.seed")

# revision identifiers, used by Alembic.
revision: str = "f33c4c0319f0"
down_revision: str | None = "281c516acf3a"
branch_labels: str | (Sequence[str] | None) = None
depends_on: str | (Sequence[str] | None) = None

_SEED_PATH = Path(__file__).resolve().parents[2] / "src" / "_seed.yml"

# Lightweight table descriptors for bulk insert/delete by name. Using
# ``sa.table`` (rather than the ORM models) keeps this data migration
# independent of the declarative registry and lets Alembic emit raw SQL.
_ARCHIVE_ROLE = sa.table(
    "src_archive_role",
    sa.Column("name", sa.String),
    sa.Column("comment", sa.String),
    sa.Column("rank", sa.Integer),
)
_BRANCH_ROLE = sa.table(
    "src_branch_role",
    sa.Column("name", sa.String),
    sa.Column("comment", sa.String),
    sa.Column("abstract", sa.Boolean),
)


def _load_seed() -> dict[str, list[dict[str, object]]]:
    """Read and parse the seed YAML, returning ``{archive_role, branch_role}``.

    A missing file logs a warning and yields an empty mapping so the
    migration is a harmless no-op rather than a hard failure.
    """
    if not _SEED_PATH.exists():
        logger.warning("Seed file %s not found; skipping role seeding.", _SEED_PATH)
        return {"archive_role": [], "branch_role": []}
    with _SEED_PATH.open("r") as fh:
        data = yload(fh)
    if not isinstance(data, dict):
        logger.warning("Seed file %s did not parse to a mapping; skipping.", _SEED_PATH)
        return {"archive_role": [], "branch_role": []}
    return {
        "archive_role": list(data.get("archive_role") or []),
        "branch_role": list(data.get("branch_role") or []),
    }


def upgrade() -> None:
    """Insert the default archive/branch role rows from ``_seed.yml``."""
    seed = _load_seed()

    arcs = [
        {
            "name": row["name"],
            "comment": row.get("comment"),
            "rank": row.get("rank"),
        }
        for row in seed["archive_role"]
    ]
    if arcs:
        op.bulk_insert(_ARCHIVE_ROLE, arcs)

    branches = [
        {
            "name": row["name"],
            "comment": row.get("comment"),
            "abstract": bool(row.get("abstract", False)),
        }
        for row in seed["branch_role"]
    ]
    if branches:
        op.bulk_insert(_BRANCH_ROLE, branches)


def downgrade() -> None:
    """Delete exactly the seeded role names (user-added roles survive)."""
    seed = _load_seed()
    arc_names = [row["name"] for row in seed["archive_role"]]
    if arc_names:
        op.execute(
            _ARCHIVE_ROLE.delete().where(_ARCHIVE_ROLE.c.name.in_(arc_names))
        )
    branch_names = [row["name"] for row in seed["branch_role"]]
    if branch_names:
        op.execute(
            _BRANCH_ROLE.delete().where(_BRANCH_ROLE.c.name.in_(branch_names))
        )
