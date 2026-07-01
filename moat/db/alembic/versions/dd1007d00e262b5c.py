"""Fix fk_label_thing to reference thing table

Revision ID: dd1007d00e262b5c
Revises: 0458af1a64ff
Create Date: 2026-06-25 00:00:00.000000+00:00

"""

from __future__ import annotations

from alembic import op

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "dd1007d00e262b5c"
down_revision: str | None = "0458af1a64ff"
branch_labels: str | (Sequence[str] | None) = None
depends_on: str | (Sequence[str] | None) = None


def upgrade() -> None:
    # fk_label_thing was erroneously created pointing to `box` instead of `thing`.
    op.drop_constraint("fk_label_thing", "label", type_="foreignkey")
    op.create_foreign_key("fk_label_thing", "label", "thing", ["thing_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_label_thing", "label", type_="foreignkey")
    op.create_foreign_key("fk_label_thing", "label", "box", ["thing_id"], ["id"])
