"""
Database schema for label printing
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from moat.db.schema import Base

class LabelTyp(Base):
    "One kind of label. Label format data are in the config file."
    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    url: Mapped[str] = mapped_column(nullable=True, comment="URL prefix if the label has a random code element", type_=String(100))
    code: Mapped[int] = mapped_column(nullable=False, comment="Initial ID code when no labels exist")

class Sheet(Base):
    "A (to-be-)printed sheet with labels."
    typ_id: Mapped[int] = mapped_column(ForeignKey("labeltyp.id", name="fk_sheet_labeltyp"), nullable=True)
    start: Mapped[int] = mapped_column(nullable=False, default=0, server_default="0", comment="Position of first label")

    typ: Mapped["LabelTyp"] = relationship()
    labels: Mapped[set["Label"]] = relationship(back_populates="sheet")
    printed: Mapped[bool] = mapped_column(default=False)

    # Sheet 1 is the printed-but-not-on-a-sheet ID.

class Label(Base):
    "A single label."
    code: Mapped[int] = mapped_column(unique=True, comment="The numeric code in the primary barcode.")
    rand: Mapped[str] = mapped_column(nullable=True, comment="random characters in the seconrady barcode URL.", type_=String(16))
    text: Mapped[str] = mapped_column(nullable=False, comment="The text on the label. May be numeric.", type_=String(200))
    typ_id: Mapped[int] = mapped_column(ForeignKey("labeltyp.id", name="fk_label_labeltyp"))
    sheet_id: Mapped[int] = mapped_column(ForeignKey("sheet.id", name="fk_label_sheet"), nullable=True)

    box_id: Mapped[int] = mapped_column(ForeignKey("box.id", name="fk_label_box"), nullable=True)
    # thing_id

    typ: Mapped["LabelTyp"] = relationship()
    sheet: Mapped["Sheet"] = relationship(back_populates="labels")

from moat.box.model import Box, BoxTyp
LabelTyp.boxtypes = relationship(BoxTyp, back_populates="labeltyp")
Label.box = relationship(Box, back_populates="labels")
