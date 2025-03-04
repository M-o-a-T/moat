"""
Database schema for collecting things
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Table, Column, Integer
from sqlalchemy.orm import Mapped, mapped_column, relationship

from moat.db.schema import Base

boxtyp_tree = Table(
    "boxtyp_tree",
    Base.metadata,
    Column("parent_id", Integer, ForeignKey("boxtyp.id", name="fk_boxtyp_parent"), primary_key=True),
    Column("child_id", Integer, ForeignKey("boxtyp.id", name="fk_boxtyp_child"), primary_key=True),
)

class BoxTyp(Base):
    "One kind of box."
    name: Mapped[str] = mapped_column(unique=True, type_=String(40))

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

class Box(Base):
    "One particular box."
    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    label_id: Mapped[int] = mapped_column(ForeignKey("label.id"))

    label: Mapped["Label"] = relationship(back_populates="box")
