"""
Database schema for collecting things
"""

from __future__ import annotations

from sqlalchemy.orm import relationship

from moat.util import NotGiven
from moat.db.schema import Base
from moat.db.util import session
from moat.label.model import Label, LabelTyp
from moat.thing.model import Thing

from .model import Box, BoxTyp

BoxTyp.labeltyp = relationship(LabelTyp, back_populates="boxtypes")
Box.labels = relationship(Label, back_populates="box", collection_class=set)
Box.things = relationship(Thing, back_populates="container", collection_class=set)


def box_apply(self, container=NotGiven, boxtyp=NotGiven, **kw):
    "?"
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self, **kw)

        if container is NotGiven:
            pass
        elif container is None:
            self.container = None
        else:
            self.container = sess.one(Box, name=container)

        if boxtyp is NotGiven:
            if self.boxtyp is None:
                raise ValueError("New boxes need a type")
        elif boxtyp is None:
            raise ValueError("Boxes need a type")
        else:
            if self.boxtyp is None:
                self.boxtyp = sess.one(BoxTyp, name=boxtyp)
            elif self.boxtyp.name != boxtyp:
                raise ValueError("Box types cannot be changed")


Box.apply = box_apply


def boxtyp_apply(self, usable, unusable, parent=(), **kw):
    "?"
    Base.apply(self, **kw)
    if usable:
        if unusable:
            raise ValueError("Can't both use and not use this type")
        self.usable = True
    elif unusable:
        self.usable = False

    for p in parent:
        if p[0] != "-":
            self.parents.add(session.get().one(BoxTyp, name=p))
        else:
            self.parents.remove(session.get().one(BoxTyp, name=p[1:]))


BoxTyp.apply = boxtyp_apply
