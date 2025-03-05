"""
Database schema for collecting things
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, Table, Column, Integer, event
from sqlalchemy.orm import Mapped, mapped_column, relationship

from moat.db.schema import Base
from moat.db.util import Session

from typing import Optional

from .model import Box, BoxTyp
from moat.label.model import Label, LabelTyp

BoxTyp.labeltyp = relationship(LabelTyp, back_populates="boxtypes")
Box.labels = relationship(Label, back_populates="box", collection_class=set)
