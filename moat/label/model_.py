"""
Database schema for label printing
"""

from __future__ import annotations

from sqlalchemy.orm import relationship

from moat.label.model import LabelTyp, Sheet, Label
from moat.box.model import Box, BoxTyp
from moat.util import NotGiven, gen_ident, al_lower
from moat.db.util import session
from moat.db.schema import Base
import random

LabelTyp.boxtypes = relationship(BoxTyp, back_populates="labeltyp", collection_class=set)
Label.box = relationship(Box, back_populates="labels")

def label_apply(self, randstr=NotGiven, randlen=NotGiven, labeltyp=NotGiven, sheet=NotGiven, **kw):
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self,**kw)


        if randstr is not NotGiven:
            if randlen is not NotGiven:
                raise ValueError("Either randomly or explicitly. Not both.")
            self.rand = ranstr
        elif randlen is not NotGiven:
            if randlen is None or randlen == 0:
                randlen=Label.rand.property.columns[0].type.length
            self.rand = gen_ident(randlen, alpabet=al_lower)

        if labeltyp is None:
            raise ValueError("Labels need a type")
        if labeltyp is NotGiven:
            if self.labeltyp is None:
                raise ValueError("New labels need a type")
        else:
            if self.labeltyp is None:
                self.labeltyp = sess.one(LabelTyp,name=labeltyp)
            elif self.labeltyp.name != labeltyp:
                raise ValueError("Label types cannot be changed")

        if sheet is not NotGiven:
            if not sheet:
                sheet = None
            if self.sheet is not None and self.sheet.printed:
                raise ValueError("Can't remove labels from a non-printed sheet")
            self.sheet_id = sheet

Label.apply = label_apply


def sheet_apply(self, labeltyp=NotGiven, **kw):
    sess = session.get()
    with sess.no_autoflush:
        Base.apply(self,**kw)

        if labeltyp is None:
            raise ValueError("Sheets need a label type")
        if labeltyp is NotGiven:
            if self.typ is None:
                raise ValueError("New sheets need a label type")
        else:
            if self.labeltyp is None:
                self.labeltyp = sess.one(LabelTyp,name=labeltyp)
            elif self.labeltyp.name != labeltyp:
                raise ValueError("A sheet's label type cannot be changed")

Sheet.apply = sheet_apply


