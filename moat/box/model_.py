"""
Database schema for collecting things
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Table, Column, Integer, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from moat.db.schema import Base
from moat.db.util import session
from moat.util import NotGiven

from typing import Optional

from .model import Box, BoxTyp
from moat.label.model import Label, LabelTyp
from moat.db.schema import Base

BoxTyp.labeltyp = relationship(LabelTyp, back_populates="boxtypes")
Box.labels = relationship(Label, back_populates="box", collection_class=set)

def box_apply(self, container=NotGiven, boxtyp=NotGiven, **kw):
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self,**kw)
        if container is not None:
            if container is NotGiven:
                self.container = None
            else:
                self.container = sess.one(Box,name=container)
        if boxtyp is None:
            raise ValueError("Boxes need a type")
        if boxtyp is NotGiven:
            if self.boxtyp is None:
                raise ValueError("New boxes need a type")
        else:
            if self.boxtyp is None:
                self.boxtyp = sess.one(BoxTyp,name=boxtyp)
            elif self.boxtyp.name != boxtyp:
                raise ValueError("Box types cannot be changed")

Box.apply = box_apply


def boxtyp_apply(self, parent=(), **kw):
    Base.apply(self,**kw)
    for p in parent:
        if p[0] != "-":
            bt.parents.add(session.get().one(BoxType,name=p))
        else:
            bt.parents.remove(session.get().one(BoxType,name=p[1:]))

BoxTyp.apply = boxtyp_apply


