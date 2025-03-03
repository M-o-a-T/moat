"""
Label printing.
"""

from __future__ import annotations

import anyio
import logging  # pylint: disable=wrong-import-position
import sys
from datetime import datetime
from functools import partial
from time import time
from moat.util import load_subgroup, CFG, ensure_cfg, merge

import asyncclick as click

from .pdf import Labels


log = logging.getLogger()


class CustomFormatter(click.HelpFormatter):
    def write_heading(self, heading):
        heading = click.style(heading, fg="yellow")
        return super().write_heading(heading)

class CustomContext(click.Context):
    formatter_class = CustomFormatter

ensure_cfg("moat.label")


@load_subgroup(prefix="moat.label", invoke_without_command=True, epilog="Run without arguments to show possible options.")
@click.option("-p","--printer",help="Printer name")
@click.option("-f","--format",help="Label format")
@click.option("-t","--type","type_", help="Label type")
@click.option("-o","--out","output", type=click.Path(dir_okay=False, readable=False, writable=True), help="Destination file", default="/tmp/moat.pdf")
@click.pass_context
@click.pass_obj
async def cli(obj,ctx, printer,format,type_, output):
    """Produce labels."""
    cfg = obj.cfg = CFG.label

    def select(key,label,sel) -> dict:
        pr = cfg[key]
        dpr = pr.pop("_default",{})
        if sel:
            pr = pr[sel]
        elif len(pr) == 1:
            pr = next(iter(pr.values()))
        else:
            print(f"Known {label}:", " ".join(pr.keys()), file=sys.stderr)
            sys.exit(1)
        merge(pr,dpr, replace=False)
        return pr

    if ctx.invoked_subcommand is None:
        print(ctx.get_help())
        def prx(kk):
            return " ".join(k for k in kk.keys() if k[0] != "_")
        print("")
        print("Printers:\n\t"+ prx(cfg.printer))
        print("Formats:\n\t"+ prx(cfg.format))
        print("Label Types:\n\t"+ prx(cfg.label))
        return

    if type_:
        if format is None:
            format = cfg.label[type_].format
        elif format != cfg.label[type_]:
            raise ValueError(f"Oops, label {type} has format {cfg.label[type_].format}. not {format}")
    pr = cfg.printer = select("printer","Printers", printer)
    fo = cfg.format = select("format","Label Formats", format)
    la = cfg.label = select("label","Label types", type_)

    obj.pdf = Labels(pr,fo,la)
    obj.filename=output


@cli.command(name="test")
@click.pass_obj
async def test(obj):
    """\
    Create a test PDF that frames first and last labels.
    """
    p=obj.pdf
    p.add_page()
    p.set_line_width(0.5)
    w,h = obj.cfg.format.size
    xx,yy = obj.cfg.format.extent

    for x in (0,xx//2,xx-1):
        for y in (0,yy//2,yy-1):
            px,py = p.label_position(x,y)
            p.rect(px, py, w, h, style=None, round_corners=True, corner_radius=2)
    p.print()

