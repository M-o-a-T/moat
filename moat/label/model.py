"""
Database schema for label printing
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from moat.db.schema import Base
from moat.db.util import session


class SheetTyp(Base):
    "One kind of form for labels. Sizes etc. are in the config file."

    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    count: Mapped[int] = mapped_column(
        nullable=False,
        comment="Number of labels per sheet",
        default=1,
        server_default="1",
    )

    labeltypes: Mapped[set[LabelTyp]] = relationship(back_populates="sheettyp")
    sheets: Mapped[set[Sheet]] = relationship(back_populates="sheettyp")

    def dump(self):  # noqa: D102
        res = super().dump()
        if self.labeltypes:
            res["labeltypes"] = [lt.name for lt in self.labeltypes]
        if self.sheets:
            res["sheets"] = [sh.id for sh in self.sheets]
        return res


class LabelTyp(Base):
    "One kind of label. Label format data are in the config file."

    name: Mapped[str] = mapped_column(unique=True, type_=String(40))
    url: Mapped[str] = mapped_column(
        nullable=True,
        comment="URL prefix if the label has a random code element",
        type_=String(100),
    )
    code: Mapped[int] = mapped_column(
        nullable=False,
        comment="Initial ID code when no labels exist",
    )

    sheettyp_id: Mapped[int] = mapped_column(
        ForeignKey("sheettyp.id", name="fk_labeltyp_sheettyp"),
        nullable=False,
    )
    sheettyp: Mapped[SheetTyp] = relationship(back_populates="labeltypes")

    labels: Mapped[set[Label]] = relationship(back_populates="labeltyp")

    def dump(self):  # noqa: D102
        res = super().dump()
        if self.labels:
            res["labels"] = len(self.labels)
            # TODO maybe group by sheet
        return res

    def next_code(self):
        """
        Return the next free code# for this label type.

        Note: After you assign the result of this function to a label, you
        need to flush to the database before calling `next_code` again.
        """
        sess = session.get()

        with sess.no_autoflush:
            (code,) = sess.execute(
                select(func.min(LabelTyp.code)).where(LabelTyp.code > self.code),
            ).first()
            scmd = select(func.max(Label.code))
            if code is not None:
                scmd = scmd.where(Label.code < code)
            (code,) = sess.execute(scmd).first()
            if code is None or code < self.code:
                return self.code
            return code + 1


class Sheet(Base):
    "A (to-be-)printed sheet with labels."

    sheettyp_id: Mapped[int] = mapped_column(
        ForeignKey("sheettyp.id", name="fk_sheet_sheettyp"),
        nullable=True,
    )

    start: Mapped[int] = mapped_column(
        nullable=False,
        default=0,
        server_default="0",
        comment="Position of first label",
    )

    sheettyp: Mapped[SheetTyp] = relationship()
    labels: Mapped[set[Label]] = relationship(back_populates="sheet")
    printed: Mapped[bool] = mapped_column(default=False)

    def dump(self):  # noqa: D102
        res = super().dump()
        if self.labeltyp is not None:
            res["typ"] = self.labeltyp.name
        if self.labels:
            res["labels"] = [f"{lab.code}:{lab.text}" for lab in self.labels]
        return res

    # Sheet -1 is the printed-but-not-on-a-sheet ID.


class Label(Base):
    "A single label."

    code: Mapped[int] = mapped_column(
        unique=True,
        comment="The numeric code in the primary barcode.",
    )
    rand: Mapped[str] = mapped_column(
        nullable=True,
        comment="random characters in the seconrady barcode URL.",
        type_=String(16),
    )
    text: Mapped[str] = mapped_column(
        nullable=False,
        comment="The text on the label. May be numeric.",
        type_=String(200),
    )
    typ_id: Mapped[int] = mapped_column(ForeignKey("labeltyp.id", name="fk_label_labeltyp"))
    sheet_id: Mapped[int] = mapped_column(
        ForeignKey("sheet.id", name="fk_label_sheet"),
        nullable=True,
    )

    box_id: Mapped[int] = mapped_column(ForeignKey("box.id", name="fk_label_box"), nullable=True)
    thing_id: Mapped[int] = mapped_column(
        ForeignKey("thing.id", name="fk_label_thing"),
        nullable=True,
    )
    # thing_id

    labeltyp: Mapped[LabelTyp] = relationship(back_populates="labels")
    sheet: Mapped[Sheet] = relationship(back_populates="labels")

    def dump(self):  # noqa: D102
        res = super().dump()
        if self.labeltyp is not None:
            res["typ"] = self.labeltyp.name
        if self.sheet is not None:
            res["sheet"] = self.sheet.id
        if self.box is not None:
            res["box"] = self.box.name
        return res
