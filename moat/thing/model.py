"""
Database schema for collecting things
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from moat.db.schema import Base


class ThingTyp(Base):
    "One kind of thing."

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    comment: Mapped[str] = mapped_column(type_=String(200), nullable=True)

    parent_id: Mapped[int] = mapped_column(
        ForeignKey("thingtyp.id", name="fk_thingtyp_typ"),
        nullable=True,
    )
    parent: Mapped[ThingTyp] = relationship(
        "ThingTyp",
        back_populates="children",
        remote_side=[id],
    )

    abstract: Mapped[bool] = mapped_column(
        nullable=False,
        default=False,
        server_default="0",
        comment="Must be False for instantiating things with this type",
    )
    children: Mapped[set[ThingTyp]] = relationship("ThingTyp", back_populates="parent")
    things: Mapped[set[Thing]] = relationship(back_populates="thingtyp")

    def dump(self):  # noqa: D102
        res = super().dump()
        if self.parent:
            res["parent"] = self.parent.name
        if self.children:
            res["child"] = [p.name for p in self.children]
        if self.things:
            res["things"] = len(self.things)
        return res


class Thing(Base):
    "One particular thing"

    id: Mapped[int] = mapped_column(primary_key=True)

    typ_id: Mapped[int] = mapped_column(ForeignKey("thingtyp.id", name="fk_thing_typ"))
    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    descr: Mapped[str] = mapped_column(type_=String(200), nullable=True)
    comment: Mapped[str] = mapped_column(type_=String(200), nullable=True)

    box_id: Mapped[int] = mapped_column(ForeignKey("box.id", name="fk_thing_box"), nullable=True)

    thingtyp: Mapped[ThingTyp] = relationship(back_populates="things")

    # possibly the location within its parent
    pos_x: Mapped[int] = mapped_column(nullable=True, comment="X position in parent")
    pos_y: Mapped[int] = mapped_column(nullable=True, comment="Y position in parent")
    pos_z: Mapped[int] = mapped_column(nullable=True, comment="Z position in parent")

    def dump(self):  # noqa: D102
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
        if self.thingtyp:
            res["typ"] = self.thingtyp.name
        return res


@event.listens_for(Thing, "before_insert")
@event.listens_for(Thing, "before_update")
def validate_thing_coords(mapper, connection, model):  # noqa: D103
    mapper, connection  # noqa:B018
    par = model.container
    if par is not None:
        par = par.boxtyp

    def chk(p):
        pp = f"pos_{p}"
        ppos = getattr(par, pp, None)

        if (pos := getattr(model, pp)) is None:
            if ppos is not None and ppos > 1:
                raise ValueError(f"Thing {model.name} needs a value for {p}")
        elif pos <= 0:
            raise ValueError(f"Thing {model.name} can't set {p} <= 0")
        elif par is None:
            raise ValueError(f"Thing {model.name} is not in a sized container")
        elif ppos is None:
            raise ValueError(f"Thing {model.name} can't have a value for {p}")
        elif ppos < pos:
            raise ValueError(f"Thing {model.name}: {p} is {pos}, max is {ppos}")

    chk("x")
    chk("y")
    chk("z")
