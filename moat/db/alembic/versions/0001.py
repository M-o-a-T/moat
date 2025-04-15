"""Add initial data"""

from __future__ import annotations
from typing import TYPE_CHECKING

from alembic import op
import sqlalchemy as sa

if TYPE_CHECKING:
    from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: str | None = "0000"
branch_labels: str | (Sequence[str] | None) = None
depends_on: str | (Sequence[str] | None) = None


def upgrade() -> None:
    from moat.db import load
    from alembic import context

    config = context.config

    meta = load(config.attributes["config"])

    st = sa.insert(meta.tables["sheet"]).values(id=-1, printed=True)
    op.execute(st)
    op.execute("commit")


def downgrade() -> None:
    S = meta.tables["sheet"]
    st = sa.delete(S).where(S.id == -1)
    op.execute(st)
    op.execute("commit")
    pass
