"""
Database schema for label printing
"""

from __future__ import annotations

from sqlalchemy.orm import relationship

from moat.util import NotGiven, al_lower, gen_ident
from moat.box.model import Box, BoxTyp
from moat.db.schema import Base
from moat.db.util import session
from moat.label.model import Label, LabelTyp, Sheet, SheetTyp
from moat.thing.model import Thing

LabelTyp.boxtypes = relationship(BoxTyp, back_populates="labeltyp", collection_class=set)
Label.box = relationship(Box, back_populates="labels")
Label.thing = relationship(Thing, back_populates="labels")


def label_apply(self, randstr=NotGiven, randlen=NotGiven, labeltyp=NotGiven, sheet=NotGiven, **kw):  # noqa: D103
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self, **kw)

        if randstr is not NotGiven:
            if randlen is not NotGiven:
                raise ValueError("Either randomly or explicitly. Not both.")
            self.rand = randstr
        elif randlen is not NotGiven:
            if randlen is None or randlen == 0:
                randlen = Label.rand.property.columns[0].type.length
            self.rand = gen_ident(randlen, alpabet=al_lower)

        if labeltyp is None:
            raise ValueError("Labels need a type")
        if labeltyp is NotGiven:
            if self.labeltyp is None:
                raise ValueError("New labels need a type")
        else:
            if self.labeltyp is None:
                self.labeltyp = sess.one(LabelTyp, name=labeltyp)
            elif self.labeltyp.name != labeltyp:
                raise ValueError("Label types cannot be changed")

        if sheet is not NotGiven:
            if not sheet:
                sheet = None
            if self.sheet is not None and self.sheet.printed:
                raise ValueError("Can't remove labels from a non-printed sheet")
            self.sheet_id = sheet


Label.apply = label_apply


def sheet_apply(self, sheettyp=NotGiven, force=False, **kw):  # noqa: D103
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self, **kw)

        if sheettyp is None:
            raise ValueError("Sheets need a format")
        if sheettyp is NotGiven:
            if self.sheettyp is None:
                raise ValueError("New sheets need a format")
        else:
            if self.sheettyp is None or force:
                self.sheettyp = sess.one(SheetTyp, name=sheettyp)
            elif self.sheettyp.name != sheettyp:
                raise ValueError("A sheet's format cannot be changed")


Sheet.apply = sheet_apply


def labeltyp_apply(self, sheettyp=NotGiven, force=False, **kw):  # noqa: D103
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self, **kw)

        if sheettyp is None:
            raise ValueError("Labels need a paper format")
        if sheettyp is NotGiven:
            if self.typ is None:
                raise ValueError("New sheets need a label type")
        else:
            if self.sheettyp is None or force:
                self.sheettyp = sess.one(SheetTyp, name=sheettyp)
            elif self.sheettyp.name != sheettyp:
                raise ValueError("A label's paper format cannot be changed")


LabelTyp.apply = labeltyp_apply
