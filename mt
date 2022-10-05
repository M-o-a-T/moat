#!/usr/bin/python3

import sys
import os

import git
# assume that sys.path[0] is the main …/moat directory

def _get_sub(r):
    r = os.path.abspath(r)
    rs = os.path.join(r,"src")
    yield rs if os.path.isdir(rs) else r
    rp = git.Repo(r)
    for rr in rp.submodules:
        yield from _get_sub(os.path.join(r,rr.path))

_pp = list(_get_sub(sys.path[0]))
sys.path[0:1] = _pp

os.environ["PYTHONPATH"] = os.pathsep.join(_pp)

import trio
import traceback
from outcome import Error

from moat.main import cmd
cmd()

