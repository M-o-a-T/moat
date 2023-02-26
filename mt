#!/usr/bin/python3

import sys
import os

import git
# assume that sys.path[0] is the main …/moat directory

try:
    import pymodbus.constants  # breaks logging setup if imported later
except ImportError:
    pass

def _get_sub(r):
    r = os.path.abspath(r)
    rs = os.path.join(r,"src")
    yield rs if os.path.isdir(rs) else r
    try:
        rp = git.Repo(r)
    except Exception as exc:
        print(exc)
        return
        # raise RuntimeError(r) from exc
    for rr in rp.submodules:
        yield from _get_sub(os.path.join(r,rr.path))

_pp = list(_get_sub(sys.path[0]))
_pp.append("/src/distkv")
sys.path[0:1] = _pp
#print(_pp)
#from moat.modbus.dev._main import cli as xx

os.environ["PYTHONPATH"] = os.pathsep.join(_pp)

import trio
import traceback
from outcome import Error

from moat.main import cmd
cmd()

