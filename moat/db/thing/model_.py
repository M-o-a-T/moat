"""
Database schema for collecting things
"""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.orm import relationship

from moat.util import NotGiven
from moat.box.model import Box
from moat.db.schema import Base
from moat.db.util import session
from moat.label.model import Label

from .model import Thing, ThingTyp

Thing.labels = relationship(Label, back_populates="thing", collection_class=set)
Thing.container = relationship(Box, back_populates="things")


def thing_apply(self, label=NotGiven, container=NotGiven, thingtyp=NotGiven, **kw):  # noqa: D103
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self, **kw)

        if container is NotGiven:
            pass
        elif container is None or container == "-":
            self.container = None
        else:
            box = sess.one(Box, name=container)
            if not box.boxtype.usable:
                raise ValueError("You can't put anything into a {box.boxtype.name !r}.")
            self.container = box

        if label is NotGiven:
            pass
        elif label is None or label == "-":
            self.label = None
        else:
            self.label = sess.one(Label, name=label)

        if thingtyp is NotGiven:
            if self.thingtyp is None:
                raise ValueError("New things need a type")
        elif thingtyp is None:
            raise ValueError("Things need a type")
        else:
            if self.thingtyp is None:
                ttyp = sess.one(ThingTyp, name=thingtyp)
                if ttyp.abstract:
                    raise ValueError("Things need a non-abstract type")
                self.thingtyp = ttyp
            elif self.thingtyp.name != thingtyp:
                raise ValueError("Thing types cannot be changed")


Thing.apply = thing_apply


def thingtyp_apply(self, parent=NotGiven, abstract=False, real=False, **kw):  # noqa: D103
    if abstract:
        if real:
            raise ValueError("A type can't be both 'abstract' and 'real'.")
        kw["abstract"] = True
    elif real:
        kw["abstract"] = False

    Base.apply(self, **kw)

    sess = session.get()

    if parent is NotGiven:
        parent = self.parent.name if self.parent is not None else None
    if parent is None:
        (n,) = sess.execute(
            select(func.count(ThingTyp.id))
            .where(ThingTyp.parent == None)  # noqa:E711
            .where(ThingTyp.name != self.name),
        ).first()
        if n:
            raise ValueError("Only one top entry allowed")
    else:
        par = sess.one(ThingTyp, name=parent)
        p = par
        while p is not None:
            if p == self:
                raise ValueError("No cycles allowed.")
            p = p.parent
        self.parent = par


ThingTyp.apply = thingtyp_apply
