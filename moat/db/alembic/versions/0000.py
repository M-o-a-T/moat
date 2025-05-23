"""Init

Revision ID: e4ed1bf705a5
Revises: 0001
Create Date: 2025-03-05 20:19:53.269117+00:00

"""

from __future__ import annotations
from typing import TYPE_CHECKING

from alembic import op
import sqlalchemy as sa

if TYPE_CHECKING:
    from collections.abc import Sequence


# revision identifiers, used by Alembic.
revision: str = "0000"
down_revision: str | None = None
branch_labels: str | (Sequence[str] | None) = None
depends_on: str | (Sequence[str] | None) = None


def upgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.create_table(
        "labeltyp",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column(
            "url",
            sa.String(length=100),
            nullable=True,
            comment="URL prefix if the label has a random code element",
        ),
        sa.Column(
            "code",
            sa.Integer(),
            nullable=False,
            comment="Initial ID code when no labels exist",
        ),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "boxtyp",
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("comment", sa.String(length=200), nullable=True),
        sa.Column("pos_x", sa.Integer(), nullable=True, comment="Max # of X positions"),
        sa.Column("pos_y", sa.Integer(), nullable=True, comment="Max # of Y positions"),
        sa.Column("pos_z", sa.Integer(), nullable=True, comment="Max # of Z positions"),
        sa.Column("labeltyp_id", sa.Integer(), nullable=True, comment="Default label"),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["labeltyp_id"], ["labeltyp.id"], name="fk_boxtyp_labeltyp"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "sheet",
        sa.Column("typ_id", sa.Integer(), nullable=True),
        sa.Column(
            "start",
            sa.Integer(),
            server_default="0",
            nullable=False,
            comment="Position of first label",
        ),
        sa.Column("printed", sa.Boolean(), nullable=False),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["typ_id"], ["labeltyp.id"], name="fk_sheet_labeltyp"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_table(
        "box",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("typ_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=40), nullable=False),
        sa.Column("container_id", sa.Integer(), nullable=True),
        sa.Column("pos_x", sa.Integer(), nullable=True, comment="X position in parent"),
        sa.Column("pos_y", sa.Integer(), nullable=True, comment="Y position in parent"),
        sa.Column("pos_z", sa.Integer(), nullable=True, comment="Z position in parent"),
        sa.ForeignKeyConstraint(["container_id"], ["box.id"], name="fk_box_container"),
        sa.ForeignKeyConstraint(["typ_id"], ["boxtyp.id"], name="fk_box_typ"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )
    op.create_table(
        "boxtyp_tree",
        sa.Column("parent_id", sa.Integer(), nullable=False),
        sa.Column("child_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["child_id"], ["boxtyp.id"], name="fk_boxtyp_child"),
        sa.ForeignKeyConstraint(["parent_id"], ["boxtyp.id"], name="fk_boxtyp_parent"),
        sa.PrimaryKeyConstraint("parent_id", "child_id"),
    )
    op.create_table(
        "label",
        sa.Column(
            "code",
            sa.Integer(),
            nullable=False,
            comment="The numeric code in the primary barcode.",
        ),
        sa.Column(
            "rand",
            sa.String(length=16),
            nullable=True,
            comment="random characters in the seconrady barcode URL.",
        ),
        sa.Column(
            "text",
            sa.String(length=200),
            nullable=False,
            comment="The text on the label. May be numeric.",
        ),
        sa.Column("typ_id", sa.Integer(), nullable=False),
        sa.Column("sheet_id", sa.Integer(), nullable=True),
        sa.Column("box_id", sa.Integer(), nullable=True),
        sa.Column("id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["box_id"], ["box.id"], name="fk_label_box"),
        sa.ForeignKeyConstraint(["sheet_id"], ["sheet.id"], name="fk_label_sheet"),
        sa.ForeignKeyConstraint(["typ_id"], ["labeltyp.id"], name="fk_label_labeltyp"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("code"),
    )
    # ### end Alembic commands ###


def downgrade() -> None:
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_table("label")
    op.drop_table("boxtyp_tree")
    op.drop_table("box")
    op.drop_table("sheet")
    op.drop_table("boxtyp")
    op.drop_table("labeltyp")
    # ### end Alembic commands ###
