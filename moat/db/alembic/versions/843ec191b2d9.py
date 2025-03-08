"""Sheet types cleanup

Revision ID: 843ec191b2d9
Revises: 3fd4e7cabdf3
Create Date: 2025-03-08 08:44:19.796867+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import mysql

# revision identifiers, used by Alembic.
revision: str = '843ec191b2d9'
down_revision: Union[str, None] = '3fd4e7cabdf3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.alter_column('labeltyp', 'sheettyp_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=False)
    op.drop_column('labeltyp', 'count')
    op.drop_constraint('fk_sheet_labeltyp', 'sheet', type_='foreignkey')
    op.drop_column('sheet', 'typ_id')
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column('sheet', sa.Column('typ_id', mysql.INTEGER(display_width=11), autoincrement=False, nullable=True))
    op.create_foreign_key('fk_sheet_labeltyp', 'sheet', 'labeltyp', ['typ_id'], ['id'])
    op.add_column('labeltyp', sa.Column('count', mysql.INTEGER(display_width=11), server_default=sa.text('1'), autoincrement=False, nullable=False, comment='Number of labels per sheet'))
    op.alter_column('labeltyp', 'sheettyp_id',
               existing_type=mysql.INTEGER(display_width=11),
               nullable=True)
    # ### end Alembic commands ###
