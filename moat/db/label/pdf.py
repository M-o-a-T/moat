"""
PDF subclass
"""

from __future__ import annotations

from fpdf import FPDF, ViewerPreferences

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.util import attrdict


class Labels(FPDF):  # noqa: D101
    def __init__(
        self,
        printer: attrdict,
        format: attrdict | None = None,  # noqa: A002
        label: attrdict | None = None,
        current_x=0,
        current_y=0,
    ):
        super().__init__()
        self.__pr = printer
        self.__fo = format
        self.__la = label
        self.__cx = current_x
        self.__cy = current_y
        self.__paged = False

        self.set_creator("MoaT Label")
        self.set_display_mode("real")
        self.viewer_preferences = ViewerPreferences(display_doc_title=False)

    def set_coord(self, cx: int, cy: int) -> None:  # noqa: D102
        self.__cx = cx
        self.__cy = cy

    def next_coord(self, format=None, label=None) -> tuple[int, int]:  # noqa: A002, D102
        if format is not None:
            self.__fo = format
        if label is not None:
            self.__la = label
        if not self.__paged:
            self.add_page()
        cx = self.__cx
        cy = self.__cy

        ncx = cx + 1
        ncy = cy
        if ncx < self.__fo.extent[0]:
            self.__cx = ncx
        else:
            self.__cx = 0
            ncy += 1
            if ncy < self.__fo.extent[1]:
                self.__cy = ncy
            else:
                self.__cy = 0
                self.__paged = False

        return cx, cy

    def label_position(self, x: int, y: int) -> tuple[float, float]:  # noqa: D102
        stp = self.__fo.stepping
        scl = self.__pr.scale
        pm = self.__pr.margin
        lm = self.__fo.margin
        return pm[0] + (lm[0] + x * stp[0]) * scl[0], pm[1] + (lm[1] + y * stp[1]) * scl[1]

    def add_page(self, printer=None, format=None, label=None):  # noqa: A002, D102
        if printer is not None:
            self.__pr = printer
        if format is not None:
            self.__fo = format
        if label is not None:
            self.__la = label
        super().add_page(format=self.__pr.size)

        self.set_auto_page_break(False, margin=0)
        self.set_margins(*self.__pr.page)
        if self.__la is not None:
            f = self.__la.font
            self.set_font(f.name, style=f.style, size=f.size)
        self.__paged = True

    def print(self, file=None):
        """
        Generate a PDF.

        If @file is given, write to it, else print directly if the printer
        is named, else return the PDF's binary data.
        """
        if file is None:
            try:
                name = self.__pr.name
            except AttributeError:
                return self.output()
        else:
            self.output(file)
            return

        buf = self.output()

        from subprocess import run  # noqa: PLC0415

        args = [
            "lpr",
            "-P",
            name,
            "-o page-bottom=0",
            "-o",
            "page-left=0",
            "-o",
            "page-right=0",
            "-o",
            "page-top=0",
            "-o",
            "print-scaling=none",
            "-o",
            "sides=one-sided",
        ]
        if "slot" in self.__pr:
            args.append("-o")
            args.append("InputSlot=" + self.__pr.slot)
        args.append(f"-P{self.__pr.name}")

        run(args, input=buf, check=True)  # noqa:S603
