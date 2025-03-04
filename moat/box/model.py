"""
Database schema for collecting things
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Table, Column, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from moat.db.schema import Base

from typing import Optional

boxtyp_tree = Table(
    "boxtyp_tree",
    Base.metadata,
    Column("parent_id", Integer, ForeignKey("boxtyp.id", name="fk_boxtyp_parent"), primary_key=True),
    Column("child_id", Integer, ForeignKey("boxtyp.id", name="fk_boxtyp_child"), primary_key=True),
)

class BoxTyp(Base):
    "One kind of box."
    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    comment: Mapped[str] = mapped_column(type_=String(200), nullable=True)

    parents: Mapped[set["BoxTyp"]] = relationship(
        "BoxTyp",
        secondary=boxtyp_tree,
        primaryjoin= "BoxTyp.id == boxtyp_tree.c.child_id",
        secondaryjoin= "BoxTyp.id == boxtyp_tree.c.parent_id",
        back_populates="children",
    )
    children: Mapped[set["BoxTyp"]] = relationship(
        "BoxTyp",
        secondary=boxtyp_tree,
        primaryjoin= "BoxTyp.id == boxtyp_tree.c.parent_id",
        secondaryjoin= "BoxTyp.id == boxtyp_tree.c.child_id",
        back_populates="parents",
    )

    # Possible locations in there
    pos_x: Mapped[int] = mapped_column(nullable=True, comment="Max # of X positions")
    pos_y: Mapped[int] = mapped_column(nullable=True, comment="Max # of Y positions")
    pos_z: Mapped[int] = mapped_column(nullable=True, comment="Max # of Z positions")

    labeltyp_id: Mapped[int] = mapped_column(ForeignKey("labeltyp.id"), nullable=True, comment="Default label")

    boxes: Mapped[set["Box"]] = relationship(back_populates="boxtyp")

    def dump(self):
        res = super().dump()
        if self.parents:
            res["parent"] = [p.name for p in self.parents]
        if self.children:
            res["child"] = [p.name for p in self.children]
        return res

class Box(Base):
    "One particular box, possibly with other boxes inside."
    id: Mapped[int] = mapped_column(primary_key=True)

    typ_id: Mapped[int] = mapped_column(ForeignKey("boxtyp.id"))
    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    label_id: Mapped[Optional[int]] = mapped_column(ForeignKey("label.id"), nullable=True)
    container_id: Mapped[int] = mapped_column(ForeignKey("box.id"), nullable=True)

    boxtyp: Mapped[BoxTyp] = relationship(back_populates="boxes")
    container: Mapped[Optional["Box"]] = relationship(back_populates="boxes", remote_side=[id])
    boxes: Mapped[set["Box"]] = relationship(back_populates="container")

    # location within its parent
    pos_x: Mapped[int] = mapped_column(nullable=True, comment="X position in parent")
    pos_y: Mapped[int] = mapped_column(nullable=True, comment="Y position in parent")
    pos_z: Mapped[int] = mapped_column(nullable=True, comment="Z position in parent")

# recursive usage

from moat.label.model import Label, LabelTyp

BoxTyp.labeltyp = relationship(LabelTyp, back_populates="boxtypes")
Box.label = relationship(Label, back_populates="boxes")
