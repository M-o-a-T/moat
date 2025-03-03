"""
PDF subclass
"""

from __future__ import annotations

from fpdf import FPDF, ViewerPreferences
from pystrich.datamatrix import DataMatrixEncoder, DataMatrixRenderer
import click
from moat.util import yload,yprint

class Labels(FPDF):

    def __init__(self, printer:attrdict, format: attrdict, label:attrdict, current_x=0, current_y=0):
        super().__init__()
        self.__pr = printer
        self.__fo = format
        self.__la = label
        self.__cx=current_x
        self.__cy=current_y
        self.__paged = False

        self.set_creator("MoaT Label")
        self.set_display_mode("real")
        self.viewer_preferences = ViewerPreferences(display_doc_title=False)

    def next_coord(self) -> tuple[int,int]:
        if not self.__paged:
            self.add_page()
            self.__paged = True
        cx=self.__cx
        cy=self.__cy

        ncx=cx+1
        ncy=cy
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

        return cx,cy

    def label_position(self,x:int,y:int) -> tuple[float,float]:
        stp = self.__fo.stepping
        scl = self.__pr.scale
        pm=self.__pr.margin
        lm=self.__fo.margin
        return pm[0]+(lm[0]+x*stp[0])*scl[0], pm[1]+(lm[1]+y*stp[1])*scl[1]

    def add_page(self):
        super().add_page(format=self.__pr.size)

        self.set_auto_page_break(False, margin=0)
        self.set_margins(*self.__pr.page)
        f=self.__la.font
        self.set_font(f.name, style=f.style, size=f.size)

    def print(self, name=None):
        if name is None:
            try:
                name=self.__pr.name
            except AttributeError:
                raise ValueError("Need a printer name") from None
        buf=self.output()

        from subprocess import run, PIPE
        args = ["lpr","-o page-bottom=0","-o","page-left=0","-o","page-right=0","-o","page-top=0","-o","print-scaling=none"]
        if "slot" in self.__pr:
            args.append("-o")
            args.append("InputSlot="+self.__pr.slot)
        args.append(f"-P{self.__pr.name}")

        run(args, input=buf, check=True)

