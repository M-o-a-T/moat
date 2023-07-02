#!/usr/bin/python3

import sys
import os

import git
# assume that sys.path[0] is the main …/moat directory

import logging
FORMAT = (
    "%(asctime)-15s %(threadName)-15s %(levelname)-8s %(module)-15s:%(lineno)-8s %(message)s"
)
logging.basicConfig(format=FORMAT, level=logging.WARNING)
#class dbg(logging.Handler):
#    def emit(self, r):
#        print(r.getMessage(), file=sys.stderr)
#        pass
#logging.root.addHandler(dbg())
#logging.getLogger("pymodbus.factory").addHandler(dbg())
#logging.getLogger("moat.modbus.client").addHandler(dbg())

def nbc(*a,**k):
    logging.warning(f"Logging: another basicConfig call: ignored {a} {k} ")
logging.basicConfig = nbc

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

