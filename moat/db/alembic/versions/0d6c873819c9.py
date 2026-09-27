"""Merge the moat.db.inv and moat.db.src branches

Revision ID: 0d6c873819c9
Revises: b7c2d9e1f4a3, f33c4c0319f0
Create Date: 2026-09-28 00:00:00.000000+00:00

"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "0d6c873819c9"
down_revision: str | (Sequence[str] | None) = ("b7c2d9e1f4a3", "f33c4c0319f0")
branch_labels: str | (Sequence[str] | None) = None
depends_on: str | (Sequence[str] | None) = None


def upgrade() -> None:
    """Nothing to do: both branches only add their own tables."""


def downgrade() -> None:
    """Nothing to do."""
