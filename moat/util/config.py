"""
This module imports possibly-partial configuration snippets.
"""

from importlib import import_module
from pathlib import Path as FSPath

from moat.util import yload, Path, attrdict

CFG = {}

def ensure_cfg(path: str|Path) -> dict:
    """
    Ensure that a submodule's default configuration is available.
    """
    if isinstance(path,str):
        path = path.split(".")

    def _load(cfg, p):
        ext = import_module(p)

        try:
            p = ext.__path__
        except AttributeError:
            p = (str(FSPath(ext.__file__).parent),)

        for d in p:
            fn = FSPath(d) / "_config.yaml"
            if fn.is_file():
                merge(cfg, yload(fn, attr=True))


    try:
        EXT = CFG.setdefault("ext",attrdict())
        EXT["moat"] = CFG

        if "logging" not in CFG:
            _load(CFG, "moat")

        cc = CFG if path[0] == "moat" else EXT
        for n in len(path):
            cc = cc.setdefault(path[n], attrdict())
            if cc:
                continue
            _load(cc, ".".join(path[:n+1]))

    finally:
        del EXT["moat"]

    return CFG
