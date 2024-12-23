"""
This module imports possibly-partial configuration snippets.
"""

from importlib import import_module
from pathlib import Path as FSPath

from .yaml import yload
from .path import Path
from .dict import attrdict
from .merge import merge

__all__ = ["CFG", "ensure_cfg"]
CFG = attrdict()


def ensure_cfg(path: str | Path, cfg=CFG) -> dict:
    """
    Ensure that a submodule's default configuration is available.
    """
    if isinstance(path, str):
        path = path.split(".")

    def _load(cfg, p):
        ext = import_module(p)

        try:
            p = ext.__path__
        except AttributeError:
            p = (str(FSPath(ext.__file__).parent),)

        for d in p:
            fn = FSPath(d) / "_cfg.yaml"
            if fn.is_file():
                merge(cfg, yload(fn, attr=True))

    try:
        EXT = cfg.setdefault("ext", attrdict())
        EXT["moat"] = cfg

        if "logging" not in cfg:
            _load(cfg, "moat")

        cc = EXT
        for n in range(len(path)):
            cc = cc.setdefault(path[n], attrdict())
            if cc:
                continue
            _load(cc, ".".join(path[: n + 1]))

    finally:
        del EXT["moat"]

    return cfg
