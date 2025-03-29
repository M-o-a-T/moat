"""Sheet types

Revision ID: 3fd4e7cabdf3
Revises: 795ad27fee3c
Create Date: 2025-03-08 07:49:38.811994+00:00

"""
from __future__ import annotations
from typing import Union
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "3fd4e7cabdf3"
down_revision: Union[str, None] = "795ad27fee3c"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "sheettyp",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column(
            "count",
            sa.Integer(),
            server_default="1",
            nullable=False,
            comment="Number of labels per sheet",
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.add_column("labeltyp", sa.Column("sheettyp_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_labeltyp_sheettyp", "labeltyp", "sheettyp", ["sheettyp_id"], ["id"])
    op.add_column("sheet", sa.Column("sheettyp_id", sa.Integer(), nullable=True))
    op.create_foreign_key("fk_sheet_sheettyp", "sheet", "sheettyp", ["sheettyp_id"], ["id"])
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_constraint("fk_sheet_sheettyp", "sheet", type_="foreignkey")
    op.drop_column("sheet", "sheettyp_id")
    op.drop_constraint("fk_labeltyp_sheettyp", "labeltyp", type_="foreignkey")
    op.drop_column("labeltyp", "sheettyp_id")
    op.drop_table("sheettyp")
    # ### end Alembic commands ###
