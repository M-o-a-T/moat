"""
Database schema for label printing
"""

from __future__ import annotations

from sqlalchemy.orm import relationship

from moat.label.model import LabelTyp,Label
from moat.box.model import Box, BoxTyp

LabelTyp.boxtypes = relationship(BoxTyp, back_populates="labeltyp", collection_class=set)
Label.box = relationship(Box, back_populates="labels")
