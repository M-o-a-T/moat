"""
Code for "python3 -mmoat" when running in the MoaT source tree.
"""
import sys
import os
from pathlib import Path

import git

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

# assume that sys.path[0] is the main …/moat directory
sys.path[0:0] = _pp

import moat
import pkgutil
moat.__path__ = pkgutil.extend_path(moat.__path__, "moat")

os.environ["PYTHONPATH"] = os.pathsep.join(_pp)

from moat.main import cmd
cmd()

