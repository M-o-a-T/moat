"""
This module imports possibly-partial configuration snippets.
"""

from __future__ import annotations

import anyio
import os
from contextvars import ContextVar
from importlib import import_module
from pathlib import Path as FSPath
from weakref import WeakSet

from moat.util import NotGiven, attrdict, combine_dict, ctx_as, merge, yload
from moat.lib.micro import ObjSequence
from moat.lib.path import P, Path

from ._reg import to_process

from collections.abc import Mapping, MutableSequence
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, ClassVar

__all__ = ["CFG", "CfgStore", "current_cfg", "monitor"]

current_cfg = ContextVar("current_cfg", default=None)


def get_base(base, root: attrdict, result: attrdict, loc: Path, here: FSPath):
    """Resolve $base keys."""
    if isinstance(base, str):
        res = load_yaml(here / base)
        merge(result, res, replace=False)
    elif isinstance(base, ObjSequence):
        cfg = attrdict()
        initial = True
        masked = []
        for v in base:
            if isinstance(v, Path) and not v.is_relative:
                if initial:
                    masked.append(v)
                else:
                    cfg = cfg.get_(v)
                continue
            initial = False
            if isinstance(v, Path):
                c2 = root.get_(v)
                if isinstance(c2, Mapping):
                    c2 = type(c2)(**c2)
            else:
                c2 = attrdict()
                get_base(v, root, c2, loc, here)
            cfg = combine_dict(cfg, c2, cls=attrdict, keep=True)  # first value wins
        for v in masked:
            cfg.delete_(v)
        merge(result, cfg, replace=False)
    elif isinstance(base, dict):
        for k, v in base.items():
            if isinstance(result, MutableSequence) and isinstance(k, int):
                if len(result) == k:
                    r = attrdict()
                    result.append(r)
                elif result[k] in (None, NotGiven):
                    r = result[k] = attrdict()
                else:
                    r = result[k]
            elif k in result:
                r = result[k]
            else:
                r = result[k] = attrdict()
            get_base(v, root, r, loc / k, here)
    else:
        raise ValueError(f"Unknown value in $base.{loc}: {base}")  # noqa:TRY004


def load_yaml(f: FSPath) -> attrdict:
    """
    Load a single config file and resolve ``$base``.
    """
    with f.open("r") as fd:
        res = yload(fd, attr=True)
    if res is None:
        return res  # empty file
    if (base := res.pop("$base", None)) is not None:
        get_base(base, res, res, Path(), f.parent)
    return res


def default_cfg(name: str | None = None, load_all: bool | None = False):
    """
    Read a YAML config file, either from the specified path
    or from a couple of default paths.
    """
    cfg: attrdict = attrdict()
    if name is None or load_all is None:
        return cfg
    cf = cfg.env = attrdict(load_all=load_all)
    seen = False

    def _cfg(path: str | FSPath):
        nonlocal seen
        if isinstance(path, str):
            path = FSPath(path)
        if seen and not cf.load_all:
            return
        if path.exists():
            try:
                cfg2 = load_yaml(path)
            except PermissionError:
                pass
            else:
                merge(cfg, cfg2, replace=False)

    if _config.TEST:
        _cfg(f"tests/cfg/{name}.yaml")
        _cfg(f"tests/cfg/{name}_add.yaml")
    else:
        cfd = os.environ.get("XDG_CONFIG_HOME", None) or os.path.expanduser("~/.config")
        _cfg(f"{cfd}/{name}/config.yaml")
        _cfg(f"{cfd}/{name}.yaml")
        _cfg(os.path.expanduser(f"~/.{name}.yaml"))

        cfds = os.environ.get("MOAT_CONFIG_DIRS", "/etc")
        for cf in cfds.split(":"):
            _cfg(f"{cf}/{name}/{name}.yaml")
            _cfg(f"{cf}/{name}.yaml")

    return cfg


def undo_ext(cfg: dict, name: str | None):
    "foo=one $root=bar=two => NAME=foo=one bar=two"
    if name is None:
        return cfg
    ext = cfg.pop("$root", attrdict())
    ext[name] = cfg
    return ext


class CFG_:
    """
    This is the singleton that refers to the current configuration.

    Attribute accesses are redirected to it.
    """

    @staticmethod
    def set_real_cfg(self, cfg: CfgStore):
        """
        Set the real configuration store.

        Args:
            cfg: The configuration store to set

        Raises:
            RuntimeError: if config is already set
        """
        if current_cfg.get() is not None:
            raise RuntimeError("Config already set")
        current_cfg.set(cfg)

    @staticmethod
    def with_config_(cfg: CfgStore):
        """
        This context manager switches to a different configuration.

        The new config is separate, *not* a superset of existing data.
        """
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

    @staticmethod
    def set_env_(key: str | Path, value: Any):
        """
        Update an environment value.

        The environment is common to all configuration stores within a program.
        """
        if isinstance(key, str):
            key = P(key)
        CfgStore.env.env.set_(key, value)
        CfgStore.updated += 1

    @staticmethod
    def __call__(*a, **k) -> CfgStore:
        """
        Initial setup; see `CfgStore` for arguments.

        Call this early in your program.
        """
        if current_cfg.get() is not None:
            raise RuntimeError("Config was already set up")
        cfg = CfgStore(*a, **k)
        current_cfg.set(cfg)
        return cfg


CFG = CFG_()


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
            Flag whether to load default config file(s): True=load all,
            False=stop after first found, None=skip entirely.

    Precendence (first option wins):
    - Command line arguments
    - *preload* argument to this class
    - environment (TODO)
    - explicit config file(s)
    - default config file(s)
    - default data from (loaded) modules
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
        here: FSPath = FSPath("."),
    ):
        self.name = name
        self.ext_name = ext or "ext"
        self.load_all = load_all
        self.cfg = []
        self.args = []
        self.here = here

        self.known.add(self)
        self.preload = preload or attrdict()

        self._result = attrdict()
        self.maybe_redo()

    @property
    def result(self) -> attrdict:
        "Returns the actual content"
        self.maybe_redo()
        return self._result

    def add(self, path: str | FSPath) -> None:
        """
        Add a config file.
        """
        src = self.here / path
        cfg = load_yaml(src)

        self.cfg.append((path, cfg))
        self._redo = True

    def mod(self, path, value) -> None:
        """Add a config modifier.

        Args:
            path: where to change.
            value: what to set the value to.

        Intermediate dictionaries are auto-generated.

        A path element of `None` adds an element to a list.

        A value of :py:obj:`NotGiven` deletes the entry.
        """
        self.args.append((path, value))
        self._redo = True

    def maybe_redo(self) -> None:
        "Rebuild the config if necessary"
        if self._redo:
            pass
        elif to_process:
            self._redo = True
        elif self.updated > self._updated:
            self._redo = True

        if self._redo:
            self.redo()

    def get_config(self, load_all: bool | None = None):
        if self.name is None and (cf := os.environ.get("CFG", None)) is not None:
            return load_yaml(cf)
        if load_all is None or not self.name:
            return attrdict()
        if (cf := os.environ.get(f"{self.name.upper()}_CFG", None)) is not None:
            return load_yaml(cf)
        return default_cfg(self.name, load_all=load_all)

    def redo(self):
        "Rebuild the config unconditionally"
        self._redo = False

        # Add any pending registrations
        # (both to_process and with_ are global)
        while to_process:
            name = to_process.pop()
            self.with_(name)

        lcfg = combine_dict(
            self.preload, self.env, *(x[1] for x in self.cfg), cls=attrdict, keep=True
        )
        try:
            load_all = lcfg.env.load_all
        except AttributeError:
            load_all = self.load_all
        res = combine_dict(
            lcfg,
            self.get_config(load_all),
            self.static,
            cls=attrdict,
            keep=True,
        )
        for p, v in self.args:
            res.set_(p, v, apply_notgiven=False)
        res = self.deref(res, self.here)
        merge(self._result, res)
        self.notify()

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
                    merge(cfg, load_yaml(fn), replace=True)

        cc = cls.static
        for n in range(len(path)):
            cc = cc.setdefault(path[n], attrdict())
            if hasattr(cc, "cfg_load_"):
                continue
            _load(cc, ".".join(path[: n + 1]))
            cc.cfg_load_ = True
            rt = cc.pop("$root", None)
            if rt is not None:
                merge(cls.static, rt, replace=True)
            cls.updated += 1

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

    def _deref_l(self, cfg: list | tuple, loc: Path, here: FSPath) -> None:
        if isinstance(cfg, tuple):
            cfg = list(cfg)
        for k, v in enumerate(cfg):
            if isinstance(v, attrdict):
                self._deref(v, loc / k, here)
            elif isinstance(v, (list, tuple)):
                self._deref_l(v, loc / k, here)

    def _deref(self, cfg: attrdict, loc: Path, here: FSPath) -> None:
        def get_(pos):
            r = self._root
            for k in pos:
                try:
                    r = r[k]
                except KeyError:
                    raise KeyError((pos, k)) from None
                if isinstance(r, Path) and r.is_relative:
                    r = get_(r)
            return r

        for k in cfg.keys():
            if not isinstance(k, str):
                continue
            if not k or k[0] != "$":
                continue
            raise ValueError(f"Unknown: {k}")

        for k, v in list(cfg.items()):
            if isinstance(v, attrdict):
                self._deref(v, loc / k, here)
            elif isinstance(v, (list, tuple)):
                self._deref_l(v, loc / k, here)
            elif isinstance(v, Path) and v.is_relative:
                cfg[k] = get_(v)

        cfg.updated_()

    def deref(self, cfg: attrdict, here: FSPath) -> None:
        """Resolve relative paths"""
        self._root = cfg
        self._deref(cfg, Path(), here)
        return cfg

    @classmethod
    def _notify_l(cls, cfg: list | tuple) -> None:
        for v in cfg:
            if isinstance(v, attrdict):
                if v.needs_post_:
                    cls._notify(v)
            elif isinstance(v, ObjSequence):
                cls._notify_l(v)

    @classmethod
    def _notify(cls, cfg: attrdict) -> None:
        for v in cfg.values():
            if isinstance(v, attrdict):
                if v.needs_post_:
                    cls._notify(v)
            elif isinstance(v, (list, tuple)):
                cls._notify_l(v)

        cfg.updated_()

    def notify(self) -> None:
        """Resolve relative paths"""
        cfg = self._result
        if cfg.needs_post_:
            self._notify(cfg)
        return cfg


class monitor:
    """
    Watch a config (sub)entry for changes.

    Usage::

        with monitor(self.cfg) as mon:
            async for _ in mon:
                self.update_config()
    """

    def __init__(self, cfg: attrdict, delay: float = 0.25):
        self.cfg = cfg
        self.delay = delay
        self.sig = anyio.Event()

    def trigger(self):
        self.sig.set()

    def __enter__(self):
        self.cfg.updated_ = self.trigger
        return self

    def __exit__(self, *tb):
        del self.cfg.updated_

    def __aiter__(self):
        return self

    async def __anext__(self):
        await self.sig.wait()
        self.sig = anyio.Event()
        while True:
            with anyio.move_on_after(self.delay):
                await self.sig.wait()
                self.sig = anyio.Event()
                continue
            break
        return self.cfg


# Access `moat.lib.config.TEST` dynamically
import moat.lib.config as _config  # noqa:E402
