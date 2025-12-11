"""
This module imports possibly-partial configuration snippets.
"""

from __future__ import annotations

import os
from contextvars import ContextVar
from importlib import import_module
from pathlib import Path as FSPath
from weakref import WeakSet

from . import NotGiven
from .ctx import ctx_as
from .dict import attrdict, combine_dict
from .merge import merge
from .path import Path
from .yaml import yload

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, ClassVar

__all__ = ["CFG", "CfgStore"]

current_cfg = ContextVar("current_cfg", default=None)


def get_base(base, root: attrdict, loc: Path) -> attrdict:
    """Resolve $base keys."""
    if isinstance(base, (list, tuple)):
        cfg = {}
        for i, v in enumerate(base):
            c2 = get_base(v, root, loc)
            if isinstance(c2, Path) and c2.is_relative:
                cfg = cfg.get_(c2)
            elif not isinstance(c2, dict):
                raise ValueError(f"Need a dict at {loc / i}")
            else:
                cfg = combine_dict(c2, cfg, cls=attrdict)  # first value wins
        return cfg
    if isinstance(base, str):
        with open(base, "r") as cf:
            res = yload(cf, attr=True)
            v = res.pop("$base", None)
            if v is not None:
                v = get_base(v, root, loc)
                merge(res, v, replace=False)
            return res
    if isinstance(base, dict):
        res = {}
        for k, v in base.items():
            res[k] = get_base(v, root, loc / k)
    if isinstance(base, Path):
        if base.is_relative:
            return base
        return root.get_(base)


def _deref_l(cfg: list | tuple, root: attrdict, loc: Path) -> None:
    if isinstance(cfg, tuple):
        cfg = list(cfg)
    for k, v in enumerate(cfg):
        if isinstance(v, attrdict):
            if v.needs_post_:
                _deref(v, root, loc / k)
        elif isinstance(v, (list, tuple)):
            _deref_l(v, root, loc / k)


def _deref(cfg: attrdict, root: attrdict, loc: Path) -> None:
    for k, v in list(cfg.items()):
        if not isinstance(k, str):
            pass
        elif not k or k[0] != "$":
            pass
        else:
            if k == "$base":
                res = get_base(v, root, loc)
                if isinstance(res, Path) and res.is_relative:
                    root.set_(loc, root.get_(res))
                else:
                    merge(cfg, res, replace=False)
            else:
                raise ValueError(f"Unknown: {k}")
            del cfg[k]
            continue

    for k, v in cfg.items():
        if isinstance(v, attrdict):
            if v.needs_post_:
                _deref(v, root, loc / k)
        elif isinstance(v, (list, tuple)):
            _deref_l(v, root, loc / k)
        elif isinstance(v, Path) and v.is_relative:
            cfg[k] = root.get_(v)


def deref(cfg: attrdict) -> None:
    """Merge $X keys"""
    if cfg.needs_post_:
        _deref(cfg, cfg, Path())


TEST = False


def default_cfg(name, ext_name="ext", load_all: bool = False):
    """
    Read a YAML config file, either from the specified path
    or from a couple of default paths.
    """
    cfg: attrdict = attrdict()

    def _cfg(path):
        nonlocal cfg
        if cfg:
            return
        if path is False:
            return
        if os.path.exists(path):
            try:
                with open(path) as cf:
                    cfg2 = yload(cf, attr=True)
            except PermissionError:
                pass
            else:
                if load_all:
                    merge(cfg, cfg2, replace=True)
                else:
                    cfg = cfg2

    if TEST:
        _cfg(f"tests/cfg/{name}.cfg")
        _cfg(f"tests/cfg/{name}_add.cfg")
    else:
        _cfg(os.path.expanduser(f"~/.config/{name}.cfg"))
        _cfg(os.path.expanduser(f"~/.{name}.cfg"))
        _cfg(f"/etc/{name}/{name}.cfg")
        _cfg(f"/etc/{name}.cfg")

    return undo_ext(cfg, name, ext_name)


def undo_ext(cfg: dict, name: str, ext_name: str):
    "foo=one ext=bar=two => moat=foo=one bar=two"
    if cfg is None:
        return attrdict()
    ext = cfg.pop(ext_name, attrdict())
    ext[name] = cfg
    return ext


class _CFG:
    def set_real_cfg(self, cfg: CfgStore):
        if current_cfg.get() is not None:
            raise RuntimeError("Config already set")
        current_cfg.set(cfg)

    @staticmethod
    def with_config(cfg):
        return ctx_as(current_cfg, cfg)

    def __getattr__(self, k):
        if k.startswith("_"):
            return object.__getattribute__(self, k)
        return getattr(current_cfg.get(), k)

    def __setattr__(self, k, v):
        if k.startswith("_"):
            return object.__setattr__(self, k, v)
        setattr(current_cfg.get(), k, v)

    def __delattr__(self, k):
        if k.startswith("_"):
            return object.__delattr__(self, k)
        delattr(current_cfg.get(), k)

    @property
    def env(self):
        return CfgStore.env.env


CFG = _CFG()


class CfgStore:
    """
    This class collects aggregated configuration data.
    It auto-syncs updates and calls updater functions.

    Args:
        name:
            The name of your code's module hierarchy. The default is of
            course "moat". The effect of this parameter is that everything
            under "moat.XX" will be stored as "XX", while other data (e.g.
            "YY.ZZ") will be stored in "ext.YY.ZZ" to avoid conflicts.
        ext:
            The prefix of the external hierarchy. Defaults to "ext". If
            your code contains a "foo.ext" subpackage you might want to
            change this.
        preload:
            Anything you'd like to add programmatically.
        load_all:
            Flag whether to load all default config file(s): True=yes,
            False=first found, None:skip.
    """

    static: ClassVar[attrdict] = attrdict()
    "static config from loaded code"

    env: ClassVar[attrdict] = attrdict(env=attrdict())
    "static config from system environment"

    updated: ClassVar[int] = 0
    "update counter for the static config"

    known: ClassVar[set[CfgStore]] = WeakSet()
    "config stores, for background updates"

    load_all: bool | None
    "flag"

    ext_name: str
    "external subdir"

    config: attrdict
    "data from config file(s)"

    preload: attrdict

    cfg: list[tuple[str, Any]]
    "config from explicit file(s)"

    args: list[tuple[Path, Any]]
    "Manual updates"

    result: attrdict
    _redo: bool = True
    _updated: int = 0

    args: attrdict

    def __init__(
        self,
        name: str | None = "moat",
        preload: attrdict | None = None,
        load_all: bool | None = False,
        ext: str | None = None,
    ):
        self.name = name
        self.ext_name = ext or "ext"
        self.load_all = load_all
        self.cfg = []
        self.args = []

        self.known.add(self)

        if load_all is None or not name:
            self.config = attrdict()
        elif (cf := os.environ.get(f"{self.name.upper()}_CFG", None)) is not None:
            with open(cf, "r") as cff:
                self.config = undo_ext(yload(cff, attr=True), self.name, self.ext_name)
        else:
            self.config = default_cfg(self.name, self.ext_name, load_all=load_all)

        self.preload = preload or attrdict()

        self._result = attrdict()
        self.maybe_redo()

    @property
    def result(self) -> attrdict:
        "Returns the actual content"
        self.maybe_redo()
        return self._result

    def add(self, path: str) -> None:
        """
        Add a config file.
        """
        with open(path) as cff:
            cfg = undo_ext(yload(cff, attr=True), self.name, self.ext_name)

        self.cfg.append((path, cfg))
        self._redo = True

    def mod(self, path, value) -> None:
        """Add a config modifier.

        Args:
            path: where to change.
            value: what to set the value to.

        Intermediate dictionaries are auto-generated.

        A path element of `None` adds an element to a list.

        A value of `NotGiven` deletes the entry.
        """
        self.args.append((path, value))
        self._redo = True

    def maybe_redo(self) -> None:
        "Rebuild the config if necessary"
        if self.updated > self._updated:
            self._redo = True

        if self._redo:
            self.redo()

    def redo(self):
        "Rebuild the config unconditionally"
        self._redo = False
        res = combine_dict(
            self.static,
            self.config,
            *(x[1] for x in self.cfg),
            self.env,
            self.preload,
            replace=True,
            cls=attrdict,
        )
        for p, v in self.args:
            res.set_(p, v)
        deref(res)
        merge(self._result, res)

    @classmethod
    def with_(cls, path: str | Path) -> None:
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
                    merge(cfg, yload(fn, attr=True), replace=True)

        cc = cls.static
        for n in range(len(path)):
            cc = cc.setdefault(path[n], attrdict())
            if "_def" in cc:
                continue
            _load(cc, ".".join(path[: n + 1]))
            cc["_def"] = True
            cls.updated += 1

        for cfg in cls.known:
            cfg.maybe_redo()

    def __getattr__(self, key):
        if key.startswith("_"):
            return object.__getattribute__(self, key)
        self.maybe_redo()
        try:
            return self._result[key]
        except KeyError:
            raise AttributeError(key) from None

    def __getitem__(self, key: Path | str):
        self.maybe_redo()
        if isinstance(key, Path):
            return self._result.get_(key)
        else:
            return self._result[key]

    def __contains__(self, key: str):
        self.maybe_redo()
        return key in self._result

    def __setitem__(self, key: Path | str, val):
        if isinstance(key, str):
            key = Path.build((str,))
        self.args.append((key, val))
        self._redo = True

    def __delitem__(self, key):
        self.args.append((key, NotGiven))
        self._redo = True
