import os
import sys
import asyncclick as click
from collections import defaultdict
from pathlib import Path
from functools import partial
import importlib
from contextvars import ContextVar

from ._dict import attrdict, combine_dict
from ._path import path_eval
from ._yaml import yload

import logging
from logging.config import dictConfig
logger = logging.getLogger(__name__)

__all__ = ["main","call_main","Loader","load_subgroup","list_ext","load_ext"]

this_load = ContextVar("this_load", default=None)

def load_one(path, name, endpoint=None, **ns):
    mod = importlib.import_module(path)
    try:
        paths = mod.__path__
    except AttributeError:
        paths = [mod.__file__]

    for p in paths:
        p = Path(p)
        fn = p / (name+".py")
        if not fn.is_file():
            fn = p / name / "__init__.py"
            if not fn.is_file():
                continue
        with open(fn) as f:
            ns["__file__"] = fn

            code = compile(f.read(), fn, "exec")
            try:
                eval(code, ns, ns)  # pylint: disable=eval-used
            except ImportError as exc:
                raise ImportError(fn) from exc
        if endpoint is not None:
            try:
                ns = ns[endpoint]
            except KeyError:
                breakpoint()
                ns
        return ns

    raise ModuleNotFoundError(f"{path}.{name}")


def _namespaces(name):
    import pkgutil

    try:
        ext = importlib.import_module(name)
    except ModuleNotFoundError:
        import pdb;pdb.set_trace()
        raise
    return pkgutil.iter_modules(ext.__path__, ext.__name__ + ".")


_ext_cache = defaultdict(dict)


def _cache_ext(ext_name):
    """List external modules

    Yields (name,path) tuples.

    TODO: This is not zip safe.
    """
    for finder, name, ispkg in _namespaces(ext_name):
        if not ispkg:
            continue
        x = name.rsplit(".", 1)[-1]
        f = os.path.join(finder.path, x)
        _ext_cache[ext_name][x] = f


def list_ext(name, func=None):
    """List external modules

    Yields (name,path) tuples.

    TODO: This is not zip safe.
    """
    if name not in _ext_cache:
        _cache_ext(name)
    if func is None:
        yield from iter(_ext_cache[name].items())
        return
    for x, f in _ext_cache[name].items():
        fn = os.path.join(f, func) + ".py"
        if not os.path.exists(fn):
            fn = os.path.join(f, func, "__init__.py")
            if not os.path.exists(fn):
                continue
        yield (x, f)


def load_ext(ext_name, name, func, endpoint=None, **kw):
    """
    Load an external module.

    Example: ``load_ext("distkv_ext","owfs","model")`` loads …/distkv_ext/owfs/model.py
    and returns its global dict. When "ep" is given it returns the entry
    point.

    Any additional keywords are added to the module dictionary.

    TODO: This is not zip safe. It also doesn't return a proper module.
    Don't use this with modules that are also loaded the regular way.
    """

    if ext_name not in _ext_cache:
        _cache_ext(ext_name)

    n = f"{ext_name}.{name}"
    past = this_load.set(n)
    try:
        if endpoint is None:
            return load_one(ext_name, name, endpoint=func, **kw)
        else:
            return load_one(n, func, endpoint=endpoint, **kw)
    finally:
        this_load.reset(past)


def load_subgroup(_fn=None, plugin=None, **kw):
    """
    as click.group, but enables loading of subcommands
    """
    def _ext(fn, **kw):
        return click.command(**kw)(fn)

    kw['cls'] = partial(Loader, _subdir=this_load.get(), _plugin=plugin)

    if _fn is None:
        return partial(_ext, **kw)
    else:
        return _ext(_fn, **kw)

class Loader(click.Group):
    """
    A Group that can load additional commands from a subfolder.

    Caller:

        from distkv.command import Loader
        from functools import partial

        @click.command(cls=partial(Loader,_plugin='command'))
        async def cmd()
            print("I am the main program")

    Sub-Command Usage (``main`` is defined for you), e.g. in ``command/subcmd.py``::

        from distkv.command import Loader
        from functools import partial

        @main.command / group()
        async def cmd(self):
            print("I am", self.name)  # prints "subcmd"
    """

    def __init__(self, *, _subdir=None, _plugin=None, **kw):
        self._util_plugin = _plugin
        self._util_subdir = _subdir
        super().__init__(**kw)

    def list_commands(self, ctx):
        rv = super().list_commands(ctx)

        subdir = getattr(self,"_util_subdir", None) or ctx.obj._sub_name

        if subdir:
            path = Path(importlib.import_module(subdir).__path__[0])
            for filename in os.listdir(path):
                if filename[0] in "._":
                    continue
                if filename.endswith(".py"):
                    rv.append(filename[:-3])
                elif (path / filename / "__init__.py").is_file():
                    rv.append(filename)

        if self._util_plugin:
            for n, _ in list_ext(ctx.obj._ext_name, self._util_plugin):
                rv.append(n)
        rv.sort()
        return rv

    def get_command(self, ctx, name):  # pylint: disable=arguments-differ
        command = super().get_command(ctx, name)
        if command is None and self._util_plugin is not None:
            try:
                plugins = ctx.obj._ext_name

                command = load_one(f"{plugins}.{name}", self._util_plugin, "cli", main=self)
            except (ModuleNotFoundError,FileNotFoundError):
                pass

        if command is None:
            subdir = getattr(self,"_util_subdir", None) or ctx.obj._sub_name
            command = load_ext(subdir, name, "cli", main=self)

        command.__name__ = name
        return command


@click.command(cls=Loader)#, __file__, "command"))
@click.option(
    "-v", "--verbose", count=True, help="Enable debugging. Use twice for more verbosity."
)
@click.option(
    "-l", "--log", multiple=True, help="Adjust log level. Example: '--log asyncactor=DEBUG'."
)
@click.option("-q", "--quiet", count=True, help="Disable debugging. Opposite of '--verbose'.")
@click.option("-c", "--cfg", type=click.File("r"), default=None, help="Configuration file (YAML).")
@click.option(
    "-C",
    "--conf",
    multiple=True,
    help="Override a config entry. Example: '-C server.bind_default.port=57586'",
)
@click.pass_context
async def main(ctx, verbose, quiet, log, cfg, conf):
    """
    This is the main command. (You might want to override this text.)

    You need to add a subcommand for this to do anything.
    """

    # Hack the configuration using command line arguments.
    for k in conf:
        try:
            k, v = k.split("=", 1)
        except ValueError:
            v = NotGiven
        else:
            try:
                v = path_eval(v)  # pylint: disable=eval-used
            except Exception:  # pylint: disable=broad-except
                pass
        c = ctx.obj.cfg
        *sl, s = k.split(".")
        for kk in sl:
            try:
                c = c[kk]
            except KeyError:
                c[kk] = attrdict()
                c = c[kk]
        if v is NotGiven:
            del c[s]
        else:
            c[s] = v

    ctx.obj.debug = max(verbose - quiet + 1, 0)

    # Configure logging. This is a somewhat arcane art.
    lcfg = ctx.obj.cfg.setdefault("logging", dict())
    lcfg.setdefault("version", 1)
    lcfg.setdefault("root", dict())["level"] = (
        "DEBUG" if verbose > 2 else "INFO" if verbose > 1 else "WARNING" if verbose else "ERROR"
    )
    for k in log:
        k, v = k.split("=")
        lcfg["loggers"].setdefault(k, {})["level"] = v
    dictConfig(lcfg)
    logging.captureWarnings(verbose > 0)


def call_main(main=None, *, name=None, ext=None, sub=None, cfg=None, CFG=None):
    """
    The main command entry point, as declared in ``setup.py``.

    main: special main function, defaults to util.main
    name: command name, defaults to {main}'s toplevel module name.
    ext: extension stub package, default to "{name}_ext"
    sub: load *.cli() from this package, default=caller if True
    cfg: configuration file, default: various locations based on {name}
    CFG: default configuration (dir or file), relative to caller
    """

    if main is None:
        main = globals()["main"]
    if name is None:
        name = main.__module__.split(".",1)[0]
    if ext is None:
        ext = f"{name}_ext"
    if sub is True:
        import inspect
        sub = inspect.currentframe().f_back.f_globals['__package__']

    main.context_settings["obj"] = obj = attrdict()
    obj._ext_name = ext
    obj._sub_name = sub

    if isinstance(CFG,str):
        p = Path(CFG)
        if not p.is_absolute():
            p = Path(main.__file__).parent / p
        with open(p, "r") as cfgf:
            CFG = yload(cfgf)
    elif CFG is None:
        CFG = {}

    obj.stdout = CFG.get("_stdout", sys.stdout)  # used for testing

    def _cfg(path):
        nonlocal cfg
        if cfg is not None:
            return
        if os.path.exists(path):
            try:
                cfg = open(path, "r")
            except PermissionError:
                pass

    if name is not None:
        _cfg(os.path.expanduser(f"~/config/{name}.cfg"))
        _cfg(os.path.expanduser(f"~/.config/{name}.cfg"))
        _cfg(os.path.expanduser(f"~/.{name}.cfg"))
        _cfg(f"/etc/{name}/{name}.cfg")
        _cfg(f"/etc/{name}.cfg")

    for n, _ in list_ext(ext):  # pragma: no cover
        try:
            CFG[n] = combine_dict(load_ext(ext, n, "config", "CFG"), CFG.get(n, {}), cls=attrdict)
        except ModuleNotFoundError:
            pass
    obj.CFG = CFG

    if cfg:
        logger.debug("Loading %s", cfg)

        cd = yload(cfg)
        if cd is None:
            obj.cfg = CFG
        else:
            obj.cfg = combine_dict(cd, CFG, cls=attrdict)
        cfg.close()
    else:
        obj.cfg = CFG
    try:
        # pylint: disable=no-value-for-parameter,unexpected-keyword-arg
        return main(standalone_mode=False, obj=obj)

    except click.exceptions.MissingParameter as exc:
        print(f"You need to provide an argument { exc.param.name.upper() !r}.\n", file=sys.stderr)
        print(exc.cmd.get_help(exc.ctx), file=sys.stderr)
        sys.exit(2)
    except click.exceptions.UsageError as exc:
        breakpoint()
        try:
            s = str(exc)
        except TypeError:
            logger.exception(repr(exc), exc_info=exc)
        else:
            print(s, file=sys.stderr)
        sys.exit(2)
    except click.exceptions.Abort:
        print("Aborted.", file=sys.stderr)
        pass
    except EnvironmentError:  # pylint: disable=try-except-raise
        raise

