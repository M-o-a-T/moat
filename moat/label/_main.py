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
from moat.util import load_subgroup, CFG, ensure_cfg, merge, option_ng, NotGiven, yprint
from moat.db import database
from .model import LabelTyp, Label, Sheet
from sqlalchemy import select as sel, func
from contextlib import nullcontext

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


@load_subgroup(prefix="moat.label")
@click.pass_context
def cli(ctx):
    """Labels for storing things."""
    obj = ctx.obj

    sess = ctx.with_resource(database(obj.cfg.db))
    ctx.with_resource(sess.begin())

    obj.session = sess


@cli.group
@click.option("--name","-n","text",type=str,help="Text on the label")
@click.option("--nr","-N",type=str,help="Scancode of the label")
@click.pass_obj
def one(obj, text, nr):
    """
    Single labels.
    """
    obj.text=text
    obj.nr=nr
    pass

@one.command(name="show")
@click.pass_obj
def show_(obj):
    """
    Show label details / list all unassigned labels.

    If a label text or code is set, show details for this label.
    Otherwise list all printed labels that are not attached to anything.
    """
    sess = obj.session

    if obj.text is None and obj.nr is None:
        seen = False
        with sess.execute(sel(Label).where(Label.box == None)) as labels:
            for label, in labels:
                seen = True
                print(label.text)
        if not seen:
            print("No label found. Use '--help'?", file=sys.stderr)
    else:
        chk = {}
        if obj.text is not None:
            chk["text"] = obj.text
        if obj.nr is not None:
            chk["code"] = obj.nr
        try:
            label = sess.one(Label, **chk)
        except KeyError:
            print("No match.", file=sys.stderr)
            sys.exit(1)
        else:
            yprint(label.dump())

def opts(c):
    c = option_ng("--Rand","-R","randstr",type=str,help="Random string")(c)
    c = option_ng("--rand","-r","randlen",type=int,help="Generate random chars")(c)
    c = option_ng("--typ","-t","labeltyp",type=str,help="Label type")(c)
    c = option_ng("--sheet","-s","sheet",type=int,help="Sheet the label is printed on")(c)
    return c

@one.command()
@opts
@click.pass_obj
def add(obj, **kw):
    """
    Add a label.
    """
    if obj.text is None:
        raise click.UsageError("The label needs a text!")

    if obj.nr is None:
        raise click.UsageError("The box needs a code!")

    label = Label(text=obj.text, code=obj.nr)
    obj.session.add(label)
    label.apply(**kw)


@one.command()
@opts
@click.pass_obj
def set(obj, **kw):
    """
    Change a label.
    """
    chk = {}
    if obj.text is not None:
        chk["text"] = obj.text
    if obj.nr is not None:
        chk["code"] = obj.nr
    if not chk:
        raise click.UsageError("Option '--name' and/or '--nr' required")
    try:
        label = obj.session.one(Label, **chk)
    except KeyError:
        print("No match.", file=sys.stderr)
        sys.exit(1)
    else:
        label.apply(**kw)



@one.command()
@click.pass_obj
def delete(obj):
    """
    Delete a label.
    """
    chk = {}
    if obj.text is not None:
        chk["text"] = obj.text
    if obj.nr is not None:
        chk["code"] = obj.nr
    if not chk:
        raise click.UsageError("Option '--name' and/or '--nr' required")
    try:
        label = obj.session.one(Label, **chk)
    except KeyError:
        print("No match.", file=sys.stderr)
        sys.exit(1)
    else:
        obj.session.delete(label)


@cli.group(name="print")
@click.pass_obj
@click.option("-p","--printer",help="Printer name")
@click.option("-t","--typ","label", help="Label type")
@click.option("-o","--out","output", type=click.Path(dir_okay=False, readable=False, writable=True), help="Destination file", default=None)
def print_(obj, printer, label, output):
    """
    Printing!
    """
    def prx(kk):
        return " ".join(k for k in kk.keys() if k[0] != "_")
    def ndef(kw):
        for k in kw.keys():
            if k != "_default":
                return k
        raise ValueError("Duh?")

    cfg=obj.cfg.label
    if printer is None and len(cfg.printer) == 2:
        printer = ndef(cfg.printer)
    if printer is None:
        prt = None
    else:
        prt = merge(cfg.printer[printer],cfg.printer["_default"], replace=False)

    if label is None and len(cfg.label) == 2:
        label = ndef(cfg.label)

    if label is None:
        lbl = None
        fmt = None
    else:
        lbl = merge(cfg.label[label],cfg.label["_default"], replace=False)
        fmt = merge(cfg.format[lbl.format], cfg.format["_default"], replace=False)

        lbl.name_=label
        fmt.name_=lbl.format
    prt.name_=printer

    obj.label = lbl
    obj.format = fmt
    obj.printer = prt

    obj.pdf = Labels(prt,fmt,lbl)
    obj.filename=output


@print_.command(name="test")
@click.pass_obj
def test(obj):
    """\
    Create a test PDF that frames first and last labels.
    """
    p=obj.pdf
    p.add_page()

    _testpage(p, obj.format)
    p.print(obj.filename)


def _testpage(p:Labels, fmt:attrdict):
    p.set_line_width(0.5)
    w,h = fmt.size
    xx,yy = fmt.extent
    for x in (0,1,xx//2,xx-1):
        for y in (0,1,yy//2,yy-1):
            px,py = p.label_position(x,y)
            p.rect(px, py, w, h, style=None, round_corners=True, corner_radius=2)


@print_.command(name="sheet")
@click.option("-t","--test", is_flag=True,help="Add test frames")
@click.argument("sheets", nargs=-1, type=int)
@click.pass_obj
def print_sheet(obj, sheets, test):
    """\
    Print these sheets.
    """
    cfg=obj.cfg.label
    p=obj.pdf
    fmt = obj.format
    lbl = obj.label
    sess=obj.session

    for sheet in sheets:
        try:
            sh = sess.one(Sheet, id=sheet)
        except KeyError:
            print(f"Sheet {sheet} does not exist.", file=sys.stderr)
            continue
        if lbl is None:
            lbl = cfg.label[sh.labeltyp.name]
            merge(lbl,cfg.label["_default"], replace=False)
            lbl.name_ = sh.labeltyp.name
        if fmt is None:
            fmt = cfg.format[lbl.format]
            merge(fmt, cfg.format["_default"], replace=False)
            fmt.name_ = lbl.format
        if len(sh.labels) == 0:
            print(f"Sheet {sheet} is empty.", file=sys.stderr)
            continue
        if sh.start >= sh.labeltyp.count:
            print(f"Sheet {sheet} is printed out.", file=sys.stderr)
            continue
        if sh.start+len(sh.labels) > sh.labeltyp.count:
            print(f"Too many labels on sheet {sheet}!", file=sys.stderr)
            continue
        if sh.labeltyp.name != lbl.name_:
            print(f"Sheet {sheet} wants format {sh.labeltyp.name}, not {lbl.name_}.", file=sys.stderr)
            continue
        if sh.labeltyp.count > (nlab := fmt.extent[0]*fmt.extent[1]):
            print(f"Labeltype {sh.labeltyp.name} wants {sh.labeltyp.count} labels but config supports {nlab}.", file=sys.stderr)
            continue

        lbl=cfg.label[sh.labeltyp.name]
        lbl.name_ = sh.labeltyp.name
        if fmt is None:
            print(f"Sheet {sh.id} wants {lbl.format}", file=sys.stderr)
        elif lbl.format != fmt.name_:
            print(f"Warning: sheet {sh.id} needs {lbl.format}, not {fmt.name_}.", file=sys.stderr)
        fmt=cfg.format[lbl.format]
        fmt.name_ = lbl.format

        for alt in (False,True):
            p.add_page(format=fmt,label=lbl)
            if test:
                _testpage(p,fmt)
            p.set_line_width(0.5)

            xm,ym = fmt.extent
            p.set_coord(sh.start%xm, sh.start//xm)
            w,h = fmt.size

            for lab in sorted(sh.labels, key=lambda x:x.text):
                x,y = p.next_coord()
                px,py = p.label_position(x,y)

                if not lbl.alternate or alt:

                    guard=5
                    txt=str(lab.code)
                    width = len(txt)
                    if width % 1:
                        width += 1
                    width = 9*width+10 +2*guard
                    width = (fmt.size[0]-lbl.bar.margin[0]-lbl.bar.margin[2])/width
                    # "width" is the space for a narrow strip, but fpdf
                    # wants a wide strip as 'w' which is 3* the width of
                    # the narrow one.
                    p.interleaved2of5(txt,
                                      x=px+lbl.bar.margin[0]+width*guard, y=py+lbl.bar.margin[1],
                                      w=width*3, h=fmt.size[1]-lbl.bar.margin[1]-lbl.bar.margin[3])
                if not lbl.alternate or not alt:
                    p.set_xy(px+lbl.text.margin[0],py+lbl.text.margin[1])
                    w = fmt.size[0]-lbl.text.margin[0]-lbl.text.margin[2]
                    h = fmt.size[1]-lbl.text.margin[1]-lbl.text.margin[3]

                    f=lbl.font
                    p.set_font(f.name, style=f.style, size=f.size)
                    tw = p.get_string_width(lab.text)
                    if tw > w:
                        p.set_font(f.name, style=f.style, size=f.size*w/tw)
                    p.cell(w,h, lab.text, align=lbl.font.align)

            if not lbl.alternate:
                break
        print(f"Printed sheet {sh.id}.")
        sh.printed=True

    if not p.page:
        print("Nothing printed.", file=sys.stderr)
        sys.exit(1)
    p.print(obj.filename)



@cli.group
@click.option("--name","-n","name",type=str,help="Text on the label")
@click.pass_obj
def typ(obj, name):
    """
    Label types.
    """
    obj.name=name
    pass

@typ.command(name="show")
@click.pass_obj
def typ_show_(obj):
    """
    Show label type details / list all label types.

    If a name is set, show details for this type.
    Otherwise list all label types.
    """
    sess = obj.session
    cfg = obj.cfg.label

    if obj.name is None:
        seen = False
        with sess.execute(sel(LabelTyp)) as labeltyps:
            for lt, in labeltyps:
                seen = True
                print(lt.name)
        if not seen:
            print("No label types found. Use '--help'?", file=sys.stderr)
    else:
        try:
            lt = sess.one(LabelTyp, name=obj.name)
        except KeyError:
            print("No match.", file=sys.stderr)
            sys.exit(1)
        else:
            res = lt.dump()
            res["config"] = d = {}
            try:
                d["label"] = lbl = cfg.label[lt.name]
            except KeyError:
                d["label"] = "? label unknown"
            else:
                d["format"] = cfg.format.get(lbl.format,"? format unknown")
            yprint(res)

def typ_opts(c):
    c = option_ng("--url","-u",type=str,help="URL prefix for lookup")(c)
    c = option_ng("--code","-c",type=int,help="Next code to assign")(c)
    c = option_ng("--count","-n",type=int,help="Labels per sheet")(c)
    return c

@typ.command(name="add")
@typ_opts
@click.pass_obj
def typ_add(obj, **kw):
    """
    Add a label type.
    """
    if obj.name is None:
        raise click.UsageError("The label type needs a name!")

    lt = LabelTyp(name=obj.name)
    obj.session.add(lt)
    lt.apply(**kw)


@typ.command(name="set")
@typ_opts
@click.pass_obj
def typ_set(obj, **kw):
    """
    Change a label type.
    """
    if obj.name is None:
        raise click.UsageError("Which label type? Use a name")
    try:
        lt = obj.session.one(LabelTyp, name=obj.name)
    except KeyError:
        print("No match.", file=sys.stderr)
        sys.exit(1)
    else:
        lt.apply(**kw)


@typ.command(name="delete")
@click.pass_obj
def typ_delete(obj):
    """
    Delete a label type.
    """
    if obj.name is None:
        raise click.UsageError("Which label type? Use a name")
    try:
        lt = obj.session.one(LabelTyp, name=obj.name)
    except KeyError:
        print("No match.", file=sys.stderr)
        sys.exit(1)
    else:
        obj.session.delete(lt)


@cli.group
@click.option("--nr","-N",type=str,help="Number of the sheet")
@click.pass_obj
def sheet(obj, nr):
    """
    Printed sheets with labels.
    """
    obj.nr=nr
    pass


@sheet.command(name="show")
@click.option("-l","--labels",is_flag=True,help="show labels")
@click.pass_obj
def sheet_show_(obj, labels):
    """
    Show sheet details / list all unprinted sheets.

    If an ID is set, show details for this sheet.
    Otherwise list all sheets that have not been printed.
    """
    sess = obj.session

    if obj.nr is None:
        seen = False
        with sess.execute(sel(Sheet, Sheet.printed==False)) as sheets:
            for sh,*_ in sheets:
                seen = True
                print(sh.id,sh.labeltyp.name if sh.labeltyp else '*')
        if not seen:
            print("No sheets found. Use '--help'?", file=sys.stderr)
    else:
        try:
            lt = sess.one(Sheet, id=obj.nr)
        except KeyError:
            print("No match.", file=sys.stderr)
            sys.exit(1)
        else:
            res = lt.dump()
            if "labels" in res and not labels:
                res["labels"] = len(res["labels"])
            yprint(res)

def sheet_opts(c):
    c = click.option("--printed","-p",is_flag=True,help="Set the sheet as printed")(c)
    c = click.option("--unprinted","-P",is_flag=True,help="Set the sheet as not printed")(c)
    c = option_ng("--typ","-t","labeltyp",type=str,help="Label type")(c)
    c = option_ng("--start","-s",type=int,help="Position to start printing at")(c)
    return c

def _pr(yes,no):
    if yes:
        if no:
            raise click.UsageError("Can't both print and not print")
        return True
    elif no:
        return False
    else:
        return NotGiven

@sheet.command(name="add")
@sheet_opts
@click.option("-f","--fill",is_flag=True,help="Fill with un-printed labels")
@click.pass_obj
def sheet_add(obj, printed, unprinted, fill, **kw):
    """
    Add a sheet.
    """
    sess=obj.session
    kw["printed"] = _pr(printed,unprinted)

    sh = Sheet(id=obj.nr)  # auto-assigned if not given
    sess.add(sh)
    sh.apply(**kw)

    if fill:
        with sess.execute(sel(Label).where(Label.sheet==None).where(Label.labeltyp==sh.labeltyp).order_by(Label.text).limit(sh.labeltyp.count)) as labels:
            for lab,*_ in labels:
                lab.sheet=sh

    if obj.nr is None:
        print(sh.id)


@sheet.command(name="set")
@sheet_opts
@click.pass_obj
@click.option("--force","-f",is_flag=True,help="Allow changing the label type")
def sheet_set(obj, printed,unprinted, **kw):
    """
    Change a sheet.
    """
    if obj.nr is None:
        raise click.UsageError("Which sheet? Use a number")
    kw["printed"] = _pr(printed,unprinted)

    try:
        sh = obj.session.one(Sheet, id=obj.nr)
    except KeyError:
        print("No match.", file=sys.stderr)
        sys.exit(1)
    else:
        sh.apply(**kw)


@sheet.command(name="gen", epilog="To remove a label, set its sheet# to zero.")
@click.option("--pattern","-p",type=str,help="Text pattern. Replaces '#'.", default='#')
@click.option("--file","-f",type=click.File("r"),help="Read texts from this file.")
@click.option("--start","-s",type=int,help="Initial sequence number (for the text).")
@click.option("--count","-n",type=int,help="Number of labels. Default: until the sheet is full.")
@click.option("--typ","-t",type=str,help="Label type; this flag creates a new sheet.")
@click.pass_obj
def sheet_place(obj, pattern,file,start,count,typ):
    """
    Generate new labels, filling a sheet.

    The label text is either read from a file or generated as a sequence.
    
    The label's scancode is autogenerated and cannot be set here.
    """

    ocount=count
    if '#' not in pattern:
        raise click.UsageError("The pattern must include a '#' character")
    if start and file:
        raise click.UsageError("Generate a sequence *or* read from a file. Not both.")
    if start is None and file is None:
        raise click.UsageError("You need to generate a sequence or read it from a file.")

    if obj.nr is None and typ is None:
        raise click.UsageError("You need to set the label type or use an existing sheet.")

    sess = obj.session
    if typ:
        sh = Sheet(id=obj.nr, labeltyp=sess.one(LabelTyp, name=typ))
        sess.add(sh)
        sess.flush()
        if obj.nr is None:
            print(f"Added sheet {sh.id}.")
    else:
        try:
            sh = sess.one(Sheet, id=obj.nr)
        except KeyError:
            print(f"No match for sheet {obj.nr}.", file=sys.stderr)
            sys.exit(1)

    maxcount = sh.labeltyp.count-sh.start-len(sh.labels)
    if count is None:
        count = maxcount
        if count <= 0:
            print(f"Sheet {sh.id} is already full.", file=sys.stderr)
            sys.exit(1)
    elif count > maxcount:
        print(f"Sheet {sh.id} has space for {maxcount} labels.", file=sys.stderr)
        count = maxcount

    code = sh.labeltyp.next_code()

    with (open(file,"r") if file else nullcontext()) as fd:
        while count:
            count -= 1
            if file:
                seq = fd.readline().strip()
            else:
                seq = str(start)
                start += 1
            if pattern:
                seq = pattern.replace("#",seq)
            
            lab=Label(code=code, labeltyp=sh.labeltyp, text=seq)
            if sh.labeltyp.url is not None:
                self.rand = gen_ident(Label.rand.property.columns[0].type.length, alpabet=al_lower)

            sh.labels.add(lab)
            code += 1
    if start is not None:
        print(f"Done. Next free seqnum: {start}")
    else:
        print(f"Created {ocount} labels.")


@sheet.command(name="place", epilog="To remove a label, set its sheet# to zero.")
@click.option("--num","-n","numeric",is_flag=True,help="Select labels by code. Default: by text")
@click.argument("labels",nargs=-1)
@click.pass_obj
def sheet_place(obj, labels, numeric):
    """
    Place labels onto a sheet.
    """
    sess = obj.session

    if obj.nr is None:
        raise click.UsageError("Which sheet? Use a number")
    try:
        sh = sess.one(Sheet, id=obj.nr)
    except KeyError:
        print("No match.", file=sys.stderr)
        sys.exit(1)

    if sh.printed:
        print("This sheet has been printed. Flush it before continuing.")
    space = sh.labeltyp.count - sh.start+len(sh.labels)
    if space < 0:
        print("This sheet is full.")
    if space < len(labels):
        print(f"This sheet has {space} free positions, not {len(labels)}.")

    for lab in labels:
        try:
            lab = sess.one(Label,code=int(lab)) if numeric else sess.one(Label,text=lab)
        except KeyError:
            print(f"Label {lab !r} not found. Skipped.")
        else:
            if lab.sheet is not None and lab.sheet_id != -1:
                if lab.sheet.id == sheet.id:
                    print(f"Label {lab.code}:{lab.text} already is on this sheet. Skipped.")
                else:
                    print(f"Label {lab.code}:{lab.text} is on sheet {lab.sheet_id}. Skipped.")
            elif lab.labeltyp != sh.labeltyp:
                print(f"Label {lab.code}:{lab.text} has type {lab.labeltyp.name}, not {sh.labeltyp.name}. Skipped.")
            else:
                lab.sheet = sh


@sheet.command(name="flush")
@click.pass_obj
def sheet_flush(obj):
    sess=obj.session

    if obj.nr is None:
        raise click.UsageError("Which sheet? Use a number")
    try:
        sh = sess.one(Sheet, id=obj.nr)
    except KeyError:
        print("No match.", file=sys.stderr)
        sys.exit(1)

    if sh.printed:
        sh.start += len(sh.labels)
    for lab in sh.labels:
        lab.sheet_id = -1 if sh.printed else None

    if not sh.printed:
        print("Cleared.")
    elif sh.start < sh.labeltyp.count:
        print("Go print more.")
    else:
        print("All done. Deleting.")
        sess.delete(sh)



@sheet.command(name="delete")
@click.pass_obj
def sheet_delete(obj):
    """
    Delete a label type.
    """
    sess = obj.session

    if obj.nr is None:
        raise click.UsageError("Which sheet? Use a number")
    try:
        sh = sess.one(Sheet, id=obj.nr)
    except KeyError:
        print("No match.", file=sys.stderr)
        sys.exit(1)
    else:
        if sh.labels:
            print("This sheet still has labels. Not deleting.", file=sys.stderr)
            sys.exit(1)

        sess.delete(sh)

