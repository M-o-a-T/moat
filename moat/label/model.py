"""
Database schema for label printing
"""

from __future__ import annotations

from sqlalchemy import ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from moat.db.schema import Base

class LabelTyp(Base):
    "One kind of label. Label format data are in the config file."
    name: Mapped[str] = mapped_column(unique=True)
    url: Mapped[str] = mapped_column(nullable=True, comment="URL prefix if the label has a random code element")
    code: Mapped[int] = mapped_column(nullable=False, comment="Initial ID code when no labels exist")

class Sheet(Base):
    "A (to-be-)printed sheet with labels."
    typ_id: Mapped[int] = mapped_column(ForeignKey("labeltyp.id"), nullable=True)
    start: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0", comment="Position of first label")

    typ: Mapped["LabelTyp"] = relationship()
    labels: Mapped[list["Label"]] = relationship(back_populates="sheet")
    printed: Mapped[bool] = mapped_column(default=False)

    # Sheet 1 is the printed-but-not-on-a-sheet ID.

class Label(Base):
    "A single label."
    code: Mapped[int] = mapped_column(unique=True, comment="The numeric code in the primary barcode.")
    rand: Mapped[str] = mapped_column(nullable=True, comment="random characters in the seconrady barcode URL.")
    text: Mapped[str] = mapped_column(nullable=False, comment="The text on the label. May be numeric.")
    typ_id: Mapped[int] = mapped_column(ForeignKey("labeltyp.id"))
    sheet_id: Mapped[int] = mapped_column(ForeignKey("sheet.id"), nullable=True)

    typ: Mapped["LabelTyp"] = relationship()
    sheet: Mapped["Sheet"] = relationship(back_populates="labels")

