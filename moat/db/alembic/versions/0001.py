"""Add initial data
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0001'
down_revision: Union[str, None] = '0000'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    from moat.db import load
    from alembic import context
    config = context.config

    meta=load(config.attributes["config"])

    st=sa.insert(meta.tables["sheet"]).values(id=-1, printed=True)
    op.execute(st)
    op.execute("commit")


def downgrade() -> None:
    S=meta.tables["sheet"]
    st=sa.delete(S).where(S.id==-1)
    op.execute(st)
    op.execute("commit")
    pass
