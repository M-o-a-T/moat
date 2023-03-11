#!/usr/bin/env python3
"""
Basic tool support

"""
import time
import logging

import asyncclick as click
from textwrap import dedent as _dedent

from moat.util import yload, attr_args, process_args, list_ext, load_subgroup, load_ext, yprint, attrdict

from .control import Model
from .mode import BaseLoader, Loader

log = logging.getLogger()

def dedent(s):
    return _dedent(s).strip()

def Loader(name,key=None):
    res = load_ext(f"moat.bms.sched.mode.{name}")
    if key is False:
        return res
    res = res.Loader
    if key is not None:
        res = getattr(res, key)
    return res


@load_subgroup(prefix="moat.bms.sched")
@click.pass_obj
@click.option("-c","--config", help="Configuration file (YAML)", type=click.Path(dir_okay=False,readable=True))
@attr_args(with_path=False,with_proxy=False)
async def cli(obj, config, **attrs):
    """Battery Manager: Scheduling"""

    cfg = obj.cfg.bms.sched
    if config:
        with open(config,"r") as f:
            cc = yload(f)
            merge(cfg, cc)
    obj.cfg.bms.sched = process_args(cfg, **attrs)


@cli.command()
@click.pass_obj
def dump(obj):
    """
    Dump the current configuration as YAML
    """
    yprint(obj.cfg.bms.sched)

@cli.command()
@click.argument("name", nargs=-1)
def modes(name):
    """List known modes / help text for a mode"""
    static = dict(
        T="""\
List of known inputs+outputs. Use T.‹name› or ‹mode›.‹name› for details.
""",
        )
    if not name:
        mn = [m for m,_ in list_ext("moat.bms.sched.mode", pkg_only=False)]
        mn.extend(static.keys())
        ml = max(len(m) for m in mn)
        for m in mn:
            if m in static:
                doc = static[m]
            else:
                try:
                    mm = Loader(m)
                except ImportError as exc:
                    doc = repr(exc)
                else:
                    doc = dedent(mm.__doc__).split('\n',1)[0]
            print(f"{m :{ml}s}  {doc}")
        return
    for m in name:
        if m == "T":
            print("T:")
            ml = max(len(x) for x in dir(BaseLoader) if not x.startswith("_"))
            for m in dir(BaseLoader):
                if m.startswith("_"):
                    continue
                doc = dedent(getattr(BaseLoader,m).__doc__).split('\n',1)[0]
                print(f"{m :{ml}s}  {doc}")
            continue
        if m.startswith("T."):
            doc = dedent(getattr(BaseLoader,m[2:]).__doc__)
        elif "." in m:
            mn,*a = m.split(".")
            mo = Loader(mn)
            for aa in a:
                mo = getattr(mo,aa)
            doc = dedent(mo.__doc__)
        else:
            m = Loader(m)
            doc = dedent(m.__doc__)
            doc += "\nImplements: "+" ".join(x for x in m.__dict__.keys() if not x.startswith("_"))

        print(f"""\
{m}:
{doc}
""")

@cli.command(
    help="""
Calculate proposed SoC by analyzing files with assumed future usage and weather / solar input.
Goal: minimize cost.
"""
)
@click.pass_obj
@click.option(
    "-a", "--all", "all_", is_flag=True, help="emit all outputs (default: first interval)"
)
@click.option(
    "-f", "--force", is_flag=True, help="Run even if we're not close to the timeslot"
)
async def analyze(obj, all_, force):
    """
    Analyze future data.
    """
    cfg = obj.cfg.bms.sched

    t = None
    if force:
        t_slot = 3600/cfg.steps
        t = time.time() + t_slot/2
        t -= t%t_slot

    m = Model(cfg, t)

    soc_cur = cfg.start.soc
    if soc_cur < 0:
        soc_fn = cfg.mode.soc
        if soc_fn is None:
            raise click.ClickException("I need to know the current SoC")
        soc_cur = await Loader(sm,"soc")(cfg)

    if all_:
        cfg.mode.result = None
        cfg.mode.results = "file"

    await m.propose(soc_cur)
