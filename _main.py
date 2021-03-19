import os
import sys
import asyncclick as click
from collections import defaultdict
from pathlib import Path
from functools import partial
import importlib
from contextvars import ContextVar
from typing import Awaitable

from ._dict import attrdict, combine_dict
from ._impl import NotGiven
from ._path import path_eval, _eval
from ._yaml import yload

import logging
from logging.config import dictConfig

logger = logging.getLogger(__name__)

__all__ = ["main_", "wrap_main", "Loader", "load_subgroup", "list_ext", "load_ext",
        "attr_args", "process_args"]

this_load = ContextVar("this_load", default=None)


def attr_args(proc):
    """
    Allow vars_/eval_/path_ args
    """
    proc = click.option("-v", "--var", "vars_", nargs=2, multiple=True, help="Parameter (name value)")(proc)
    proc = click.option("-e", "--eval", "eval_", nargs=2, multiple=True, help="Parameter (name value), evaluated")(proc)
    proc = click.option("-p", "--path", "path_", nargs=2, multiple=True, help="Parameter (name value), as path")(proc)
    return proc


def process_args(vars_, eval_, path_, vd, vs=None):
    """
    process vars_+eval_+path_ args.

    Arguments:
        vars_, eval_, path_: from the function's arguments
        vd: dict to modify
        vs: if given: set of vars
    Returns:
        number of arguments modified
    """
    n = 0
    for k, v in vars_:
        if vs is not None:
            vs.add(k)
        vd[k] = v
        n += 1
    for k, v in eval_:
        if vs is not None:
            vs.add(k)
        if v == "-":
            vd.pop(k, None)
        elif v == "/":
            vd.pop(k, None)
            if vs is not None:
                vs.discard(k)
        else:
            vd[k] = _eval(v)
        n += 1
    for k, v in path_:
        if vs is not None:
            vs.add(k)
        vd[k] = P(v)
        n += 1
    return n


def load_one(path, name, endpoint=None):
    mod = importlib.import_module(f"{path}.{name}")
    if endpoint is not None:
        mod = getattr(mod, endpoint)
    return mod


def _namespaces(name):
    import pkgutil

    ext = importlib.import_module(name)
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
        try:
            _cache_ext(name)
        except ModuleNotFoundError:
            pass
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


def load_ext(ext_name, name, func=None, endpoint=None):
    """
    Load an external module.

    Example: ``load_ext("distkv_ext","owfs","model")`` loads …/distkv_ext/owfs/model.py
    and returns its global dict. When "ep" is given it returns the entry
    point.

    Any additional keywords are added to the module dictionary.

    TODO: This doesn't yet return a proper module.
    Don't use this with modules that are also loaded the regular way.
    """

    if ext_name not in _ext_cache:
        _cache_ext(ext_name)

    n = f"{ext_name}.{name}"
    past = this_load.set(n)
    try:
        if endpoint is None:
            return load_one(ext_name, name, endpoint=func)
        else:
            return load_one(n, func, endpoint=endpoint)
    finally:
        this_load.reset(past)


def load_subgroup(_fn=None, plugin=None, **kw):
    """
    as click.group, but enables loading of subcommands
    """

    def _ext(fn, **kw):
        return click.command(**kw)(fn)

    kw["cls"] = partial(kw.get("cls",Loader), _subdir=this_load.get(), _plugin=plugin)

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

        subdir = getattr(self, "_util_subdir", None) or ctx.obj._sub_name

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

                command = load_one(f"{plugins}.{name}", self._util_plugin, "cli")
            except (ModuleNotFoundError, FileNotFoundError):
                pass

        if command is None:
            subdir = getattr(self, "_util_subdir", None) or ctx.obj._sub_name
            command = load_ext(subdir, name, "cli")

        command.__name__ = command.name = name
        return command


class MainLoader(Loader):
    """
    A special loader that runs the main setup code even if there's a
    subcommand with "--help".
    """

    async def invoke(self, ctx):
        if ctx.obj is None:
            await ctx.invoke(self.callback, **ctx.params)
        return await super().invoke(ctx)


#
# The following part is annoying.
#
# There are two ways this can start up.
# (a) `main_` is the "real" main function. It sets up the Click environment and then
#     starts anyio and runs the function body, which calls `wrap_main`
#     synchronously to set up our object.
#
# (b) `wrap_main` is used as a wrapper, used mainly for testing. It sets up the context
#     and then returns "main_.main()", which is an awaitable, thus
#     `wrap_main` acts as an async function.


@load_subgroup(
    plugin="main", cls=MainLoader, add_help_option=False, invoke_without_command=True
)  # , __file__, "command"))
@click.option("-v", "--verbose", count=True, help="Be more verbose. Can be used multiple times.")
@click.option("-q", "--quiet", count=True, help="Be less verbose. Opposite of '--verbose'.")
@click.option("-D", "--debug", count=True, help="Enable debug speed-ups (smaller keys etc).")
@click.option(
    "-l", "--log", multiple=True, help="Adjust log level. Example: '--log asyncactor=DEBUG'."
)
@click.option("-c", "--cfg", type=click.File("r"), default=None, help="Configuration file (YAML).")
@click.option(
    "-C",
    "--conf",
    multiple=True,
    help="Override a config entry. Example: '-C server.bind_default.port=57586'",
)
@click.option(
    "-h", "-?", "--help", is_flag=True, help="Show help. Subcommands only understand '--help'."
)
@click.pass_context
async def main_(ctx, verbose, quiet, help=False, **kv):  # pylint: disable=redefined-builtin
    """
    This is the main command. (You might want to override this text.)

    You need to add a subcommand for this to do anything.
    """

    # The above `MainLoader.invoke` call causes this code to be called
    # twice instead of never.
    if ctx.obj is not None:
        return
    wrap_main(ctx=ctx, verbose=verbose - quiet, **kv)
    if help or ctx.invoked_subcommand is None and not ctx.protected_args:
        print(ctx.get_help())
        ctx.exit()


def wrap_main(  # pylint: disable=redefined-builtin
    main=main_,
    *,
    name=None,
    ext=None,
    sub=None,
    conf=(),
    cfg=None,
    CFG=None,
    args=None,
    wrap=False,
    verbose=1,
    debug=0,
    log=(),
    ctx=None,
    help=None,
) -> Awaitable:
    """
    The main command entry point, as declared in ``setup.py``.

    main: special main function, defaults to .util.main_
    name: command name, defaults to {main}'s toplevel module name.
    ext: extension stub package, default to "{name}_ext"
    sub: load *.cli() from this package, default=caller if True
    conf: a list of additional config changes
    cfg: configuration file, default: various locations based on {name}, False=don't load
    CFG: default configuration (dir or file), relative to caller
         Default: try to load from name.default
    wrap: this is a subcommand. Don't set up logging, return the awaitable.
    args: Argument list if called from a test, `None` otherwise.
    help: Main help text of your code.
    """

    if name is None:
        name = (main or main_).__module__.split(".", 1)[0]
    if ext is None:
        ext = f"{name}_ext"
    if sub is True:
        import inspect

        sub = inspect.currentframe().f_back.f_globals["__package__"]
    elif sub is None:
        sub = __name__.split(".", 1)[0] + ".command"

    obj = getattr(ctx, "obj", None)
    if obj is None:
        obj = attrdict()
    if main is None:
        if help is not None:
            raise RuntimeError("You can't set the help text this way")
    else:
        main.context_settings["obj"] = obj
        if help is not None:
            main.help = help
    obj._ext_name = ext
    obj._sub_name = sub

    merge_cfg = True
    if isinstance(CFG, str):
        p = Path(CFG)
        if not p.is_absolute():
            p = Path((main or main_).__file__).parent / p
        with open(p, "r") as cfgf:
            CFG = yload(cfgf)
    elif CFG is None:
        try:
            CFG = importlib.import_module(f"{name}.default").CFG
        except (ImportError, AttributeError):
            CFG = {}
    CFG = attrdict(**CFG)  # shallow copy

    for n, _ in list_ext(ext):
        try:
            CFG[n] = combine_dict(
                load_ext(ext, n, "config", "CFG"), CFG.get(n, {}), cls=attrdict
            )
        except ModuleNotFoundError:
            pass

    else:
        merge_cfg = False

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

    if name is not None and cfg is not False:
        _cfg(os.path.expanduser(f"~/config/{name}.cfg"))
        _cfg(os.path.expanduser(f"~/.config/{name}.cfg"))
        _cfg(os.path.expanduser(f"~/.{name}.cfg"))
        _cfg(f"/etc/{name}/{name}.cfg")
        _cfg(f"/etc/{name}.cfg")

    if merge_cfg:
        for n, _ in list_ext(ext):  # pragma: no cover
            try:
                CFG[n] = combine_dict(
                    load_ext(ext, n, "config", "CFG"), CFG.get(n, {}), cls=attrdict
                )
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

    obj.debug = verbose
    obj.DEBUG = debug

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
        c = obj.cfg
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

    if not wrap:
        # Configure logging. This is a somewhat arcane art.
        lcfg = obj.cfg.setdefault("logging", dict())
        lcfg.setdefault("version", 1)
        lcfg.setdefault("root", dict())["level"] = (
            "DEBUG"
            if verbose > 2
            else "INFO"
            if verbose > 1
            else "WARNING"
            if verbose
            else "ERROR"
        )
        for k in log:
            k, v = k.split("=")
            lcfg["loggers"].setdefault(k, {})["level"] = v
        dictConfig(lcfg)
        logging.captureWarnings(verbose > 0)

    obj.logger = logging.getLogger(name)

    try:
        # pylint: disable=no-value-for-parameter,unexpected-keyword-arg
        # NOTE this return an awaitable
        if ctx is not None:
            ctx.obj = obj
        elif main is not None:
            if wrap:
                main = main.main
            return main(args=args, standalone_mode=False, obj=obj)

    except click.exceptions.MissingParameter as exc:
        print(f"You need to provide an argument { exc.param.name.upper() !r}.\n", file=sys.stderr)
        print(exc.cmd.get_help(exc.ctx), file=sys.stderr)
        sys.exit(2)
    except click.exceptions.UsageError as exc:
        try:
            s = str(exc)
        except TypeError:
            logger.exception(repr(exc), exc_info=exc)
        else:
            print(s, file=sys.stderr)
        sys.exit(2)
    except click.exceptions.Abort:
        print("Aborted.", file=sys.stderr)
