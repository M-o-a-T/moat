"""
Code for "python3 -mmoat"
"""
import sys
import os
from pathlib import Path

import git
# assume that sys.path[0] is the main …/moat directory

try:
    import pymodbus.constants  # breaks logging setup if imported later
except ImportError:
    pass

def _get_sub(r):
    r = os.path.abspath(r)
    if "/lib/" in r:
        return
    rs = os.path.join(r,"src")
    yield rs if os.path.isdir(rs) else r
    try:
        rp = git.Repo(r)
    except Exception as exc:
        raise RuntimeError(r) from exc
    for rr in rp.submodules:
        yield from _get_sub(os.path.join(r,rr.path))

md = Path(__file__).parents[1]
_pp = list(_get_sub(md))
_pp.append(str(md))
sys.path[0:0] = _pp
#from moat.modbus.dev._main import cli as xx

import moat
import pkgutil
moat.__path__ = pkgutil.extend_path(moat.__path__, "moat")


os.environ["PYTHONPATH"] = os.pathsep.join(_pp)

import trio
import traceback
from outcome import Error

for x in sys.path:
    print(x)
from moat.main import cmd
cmd()

