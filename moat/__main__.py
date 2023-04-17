"""
Code for "python3 -mmoat" when running in the MoaT source tree.
"""
import sys
import os
from pathlib import Path

import git

def _get_sub(r):
    if "lib" in r.parts and not r.is_relative_to(md/"lib"):
        return
    rs = r/"src"
    yield (rs if rs.is_dir() else r)
    try:
        rp = git.Repo(r)
    except Exception as exc:
        raise RuntimeError(r) from exc
    for rr in rp.submodules:
        yield from _get_sub(r/rr.path)

md = Path(__file__).absolute().parents[1]
if (md/".git").exists():
    _pp = list(_get_sub(md))
    _pp.append(str(md))

    # assume that sys.path[0] is the main …/moat directory
    sys.path[0:0] = (str(x) for x in _pp)

    import moat
    import pkgutil

    # only consider local packages
    moat.__path__ = [p for p in pkgutil.extend_path([moat.__path__[0]], "moat")
            if Path(p).is_relative_to(md)]

    os.environ["PYTHONPATH"] = os.pathsep.join(str(Path(x).parent) for x in _pp)

from moat.main import cmd
cmd()

