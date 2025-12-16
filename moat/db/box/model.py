"""
Database schema for collecting things
"""

from __future__ import annotations

from sqlalchemy import Column, ForeignKey, Integer, String, Table, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from moat.db.schema import Base

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any

boxtyp_tree = Table(
    "boxtyp_tree",
    Base.metadata,
    Column(
        "parent_id",
        Integer,
        ForeignKey("boxtyp.id", name="fk_boxtyp_parent"),
        primary_key=True,
    ),
    Column("child_id", Integer, ForeignKey("boxtyp.id", name="fk_boxtyp_child"), primary_key=True),
)


class BoxTyp(Base):
    "One kind of box."

    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    comment: Mapped[str] = mapped_column(type_=String(200), nullable=True)

    parents: Mapped[set[BoxTyp]] = relationship(
        "BoxTyp",
        secondary=boxtyp_tree,
        primaryjoin="BoxTyp.id == boxtyp_tree.c.child_id",
        secondaryjoin="BoxTyp.id == boxtyp_tree.c.parent_id",
        back_populates="children",
    )
    children: Mapped[set[BoxTyp]] = relationship(
        "BoxTyp",
        secondary=boxtyp_tree,
        primaryjoin="BoxTyp.id == boxtyp_tree.c.parent_id",
        secondaryjoin="BoxTyp.id == boxtyp_tree.c.child_id",
        back_populates="parents",
    )
    usable: Mapped[bool] = mapped_column(
        nullable=False,
        default=True,
        server_default="1",
        comment="Can you put things directly into this?",
    )

    # Possible locations in there
    pos_x: Mapped[int] = mapped_column(nullable=True, comment="Max # of X positions")
    pos_y: Mapped[int] = mapped_column(nullable=True, comment="Max # of Y positions")
    pos_z: Mapped[int] = mapped_column(nullable=True, comment="Max # of Z positions")

    labeltyp_id: Mapped[int] = mapped_column(
        ForeignKey("labeltyp.id", name="fk_boxtyp_labeltyp"),
        nullable=True,
        comment="Default label",
    )

    boxes: Mapped[set[Box]] = relationship(back_populates="boxtyp")

    def dump(self) -> dict[str, Any]:
        "Standard info dump"
        res = super().dump()
        res.pop("pos_x", None)
        res.pop("pos_y", None)
        res.pop("pos_z", None)
        if self.pos_x or self.pos_y or self.pos_z:
            res["size"] = [self.pos_x, self.pos_y, self.pos_z]
        if self.parents:
            res["parent"] = [p.name for p in self.parents]
        if self.children:
            res["child"] = [p.name for p in self.children]
        return res


class Box(Base):
    "One particular box, possibly with other boxes inside."

    id: Mapped[int] = mapped_column(primary_key=True)

    typ_id: Mapped[int] = mapped_column(ForeignKey("boxtyp.id", name="fk_box_typ"))
    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    container_id: Mapped[int] = mapped_column(
        ForeignKey("box.id", name="fk_box_container"),
        nullable=True,
    )

    boxtyp: Mapped[BoxTyp] = relationship(back_populates="boxes")
    container: Mapped[Box | None] = relationship(back_populates="boxes", remote_side=[id])
    boxes: Mapped[set[Box]] = relationship(back_populates="container")

    # location within its parent
    pos_x: Mapped[int] = mapped_column(nullable=True, comment="X position in parent")
    pos_y: Mapped[int] = mapped_column(nullable=True, comment="Y position in parent")
    pos_z: Mapped[int] = mapped_column(nullable=True, comment="Z position in parent")

    def dump(self) -> dict[str, Any]:
        "Standard info dump"
        res = super().dump()
        res.pop("pos_x", None)
        res.pop("pos_y", None)
        res.pop("pos_z", None)
        if self.pos_x or self.pos_y or self.pos_z:
            res["pos"] = [self.pos_x, self.pos_y, self.pos_z]
        if self.container is not None:
            res["in"] = self.container.name
        if self.labels:
            res["labels"] = [f"{lab.id}:{lab.text}" for lab in self.labels]
        if self.boxes:
            res["content"] = sorted([box.name for box in self.boxes])
        if self.boxtyp:
            res["typ"] = self.boxtyp.name
        return res


@event.listens_for(Box, "before_insert")
@event.listens_for(Box, "before_update")
def validate_box_coords(mapper, connection, model):
    "Validator for box position"
    mapper, connection  # noqa:B018
    par = model.container
    if par is not None:
        par = par.boxtyp

    def chk(p):
        pp = f"pos_{p}"
        ppos = getattr(par, pp, None)

        if (pos := getattr(model, pp)) is None:
            if ppos is not None and ppos > 1:
                raise ValueError(f"Box {model.name} needs a value for {p}")
        elif pos <= 0:
            raise ValueError(f"Box {model.name} can't set {p} <= 0")
        elif par is None:
            raise ValueError(f"Box {model.name} is not in a sized container")
        elif ppos is None:
            raise ValueError(f"Box {model.name} can't have a value for {p}")
        elif ppos < pos:
            raise ValueError(f"Box {model.name}: {p} is {pos}, max is {ppos}")

    chk("x")
    chk("y")
    chk("z")
