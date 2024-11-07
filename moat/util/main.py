"""
Support for main program, argv, etc.
"""

from __future__ import annotations

import importlib
import logging
import logging.config
import os
import sys
from collections import defaultdict
from collections.abc import Mapping
from contextlib import suppress
from contextvars import ContextVar
from functools import partial
from pathlib import Path as FSPath

import asyncclick as click

from .dict import attrdict, to_attrdict
from .exc import ungroup
from .impl import NotGiven
from .merge import merge

try:
    from .msgpack import Proxy
except ImportError:
    Proxy = None
from .path import P, path_eval
from .yaml import yload

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Awaitable  # noqa:UP035

logger = logging.getLogger("_loader")

__all__ = [
    "main_",
    "read_cfg",
    "load_cfg",
    "wrap_main",
    "Loader",
    "load_subgroup",
    "list_ext",
    "load_ext",
    "attr_args",
    "process_args",
]

this_load = ContextVar("this_load", default=None)

NoneType = type(None)


def _no_config(*a, **k):  # noqa:ARG001
    import warnings

    warnings.warn("Call to logging config ignored", stacklevel=2)


def attr_args(proc=None, with_path=True, with_eval=True, with_proxy=False, par_name="Parameter"):
    """
    Attach the standard ``-v``/``-e``/``-p`` arguments to a ``click.command``.
    Passes ``vars_``/``eval_``/``path_`` args.

    Use `attr_args(with_path=False)` to skip path arguments. Ditto for
    `with_eval`.
    """

    def _proc(proc):
        args = (
            (
                "-p",
                "--path",
            )
            if with_path
            else ("--hidden_path",)
        )
        proc = click.option(
            *args,
            "path_",
            nargs=2,
            type=(P, P),
            multiple=True,
            help=f"{par_name} (name value), as path",
            hidden=not with_path,
        )(proc)

        args = (
            (
                "-e",
                "--eval",
            )
            if with_eval
            else ("--hidden_eval",)
        )
        proc = click.option(
            *args,
            "eval_",
            nargs=2,
            type=(P, str),
            multiple=True,
            help=f"{par_name} (name value), evaluated",
            hidden=not with_eval,
        )(proc)

        proc = click.option(
            "-v",
            "--var",
            "vars_",
            nargs=2,
            type=(P, str),
            multiple=True,
            help=f"{par_name} (name value)",
        )(proc)

        if with_proxy:
            proc = click.option(
                "-P",
                "--proxy",
                "proxy_",
                nargs=2,
                type=(P, str),
                multiple=True,
                help="Remote proxy (name value)",
            )(proc)

        return proc

    if proc is None:
        return _proc
    else:
        return _proc(proc)


def process_args(val, vars_=(), eval_=(), path_=(), proxy_=(), no_path=False, vs=None):
    """
    process ``vars_``/``eval_``/``path_``/``proxy_`` args.

    Arguments:
        vd: dict to modify
        vars_, eval_, path_, proxy_: via `attr_args`
        vs: if given: set of vars
    Returns:
        the new value.
    """
    n = 0
    # otherwise these are assumes to be empty tuples.
    if isinstance(vars_, Mapping):
        vars_ = vars_.items()
    if isinstance(eval_, Mapping):
        eval_ = eval_.items()
    if isinstance(path_, Mapping):
        path_ = path_.items()
    if isinstance(proxy_, Mapping):
        proxy_ = proxy_.items()

    def data():
        for k, v in vars_:
            yield k, v
        for k, v in eval_:
            # ruff:noqa:PLW2901 # var overwritten
            if v == "-":
                v = NotGiven
            elif v == "/":  # pylint: disable=W0631
                if vs is None:
                    raise click.BadOptionUsage(
                        option_name=k,
                        message="A slash value doesn't work here.",
                    )
                v = NoneType
            else:
                v = path_eval(v)  # pylint: disable=W0631
            yield k, v
        for k, v in path_:
            v = P(v)
            if no_path:
                v = tuple(v)
            yield k, v
        if proxy_:
            if Proxy is None:
                raise ImportError("msgpack")
            for k, v in proxy_:
                v = Proxy(v)
                yield k, v

    for k, v in data():
        if not k:
            if vs is not None:
                raise click.BadOptionUsage(
                    option_name=k,
                    message="You can't use empty paths here.",
                )
            if n:
                raise click.BadOptionUsage(
                    option_name=k,
                    message="Setting a single value conflicts.",
                )
            val = v
            n = -1
        elif n < 0:
            raise click.BadOptionUsage(option_name=k, message="Setting a single value conflicts.")
        else:
            if isinstance(k, str):
                k = P(k)
            if not isinstance(val, Mapping):
                val = attrdict()
            if vs is not None:
                vs.add(str(k))
            if v is NotGiven:
                val = attrdict._delete(val, k)  # pylint: disable=protected-access
            elif v is NoneType:
                val = attrdict._delete(val, k)  # pylint: disable=protected-access
                vs.discard(str(k))
            else:
                val = attrdict._update(val, k, v)  # pylint: disable=protected-access
            n += 1
    return val


def read_cfg(name, path):
    """
    Read a YAML config file, either from the specified path
    or from a couple of default paths.
    """
    cfg = None

    def _cfg(path):
        nonlocal cfg
        if cfg is not None:
            return
        if path is False:
            return
        if os.path.exists(path):
            try:
                with open(path) as cf:
                    cfg = yload(cf, attr=True)
            except PermissionError:
                pass

    if name is not None and cfg is not False:
        if path is not None:
            _cfg(path)
        else:
            _cfg(os.path.expanduser(f"~/config/{name}.cfg"))
            _cfg(os.path.expanduser(f"~/.config/{name}.cfg"))
            _cfg(os.path.expanduser(f"~/.{name}.cfg"))
            _cfg(f"/etc/{name}/{name}.cfg")
            _cfg(f"/etc/{name}.cfg")

    return cfg


def load_ext(name, *attr, err=False):
    """
    Load a module
    """
    path = name.split(".")
    path.extend(attr[:-1])
    dp = ".".join(path)
    dpe = ".".join(path[:-1])
    try:
        mod = importlib.import_module(dp)
    except ModuleNotFoundError as exc:
        if err:
            raise
        if err is not None:
            logger.debug("Err %s: %r", dp, exc)
        if (
            exc.name != dp and exc.name != dpe and not exc.name.startswith(f"{dp}._")  # pylint: disable=no-member ## duh?
        ):
            raise
        return None
    except FileNotFoundError:
        if err:
            raise
        return None
    else:
        if attr:
            try:
                mod = getattr(mod, attr[-1])
            except AttributeError:
                if err:
                    raise

                logger.debug("Err %s.%s", dp, attr[-1])
                return None
        return mod


def load_cfg(name):
    """
    Load a module's configuration
    """
    cf = load_ext(name, "_config", "CFG", err=None)
    if cf is None:
        cf = load_ext(name, "config", "CFG", err=None)
    if cf is None:
        cf = {}
        ext = sys.modules[name]
        try:
            p = ext.__path__
        except AttributeError:
            p = (str(FSPath(ext.__file__).parent),)
        for d in p:
            fn = FSPath(d) / "_config.yaml"
            if fn.is_file():
                merge(cf, yload(fn, attr=True))
    return cf


def _namespaces(name):
    import pkgutil  # pylint: disable=import-outside-toplevel

    try:
        ext = importlib.import_module(name)
    except ModuleNotFoundError:
        logger.debug("No NS: %s", name)
        return ()
    try:
        p = ext.__path__
    except AttributeError:
        p = (str(FSPath(ext.__file__).parent),)
    logger.debug("NS: %s %s", name, p)
    return pkgutil.iter_modules(p, ext.__name__ + ".")


_ext_cache = defaultdict(dict)


def _cache_ext(ext_name, pkg_only):
    """List external modules

    Yields (name,path) tuples.

    TODO: This is not zip safe.
    """
    for finder, name, ispkg in _namespaces(ext_name):
        if pkg_only and not ispkg:
            logger.debug("ExtNoC %s", name)
            continue
        logger.debug("ExtC %s", name)
        x = name.rsplit(".", 1)[-1]
        f = FSPath(finder.path) / x
        _ext_cache[ext_name][x] = f


def list_ext(name, func=None, pkg_only=True):
    """List external modules

    Yields (name,path) tuples.

    TODO: This is not zip safe.
    """
    logger.debug("List Ext %s (%s)", name, func)
    if name not in _ext_cache:
        with suppress(ModuleNotFoundError):
            _cache_ext(name, pkg_only)
    if func is None:
        for a, b in _ext_cache[name].items():
            logger.debug("Found %s %s", a, b)
            yield a, b
        return

    for x, f in _ext_cache[name].items():
        if (f / ".no_load").is_file():
            logger.debug("Skip %s", f)
            continue
        fn = f / (func + ".py")
        if not fn.is_file():
            fn = f / func / "__init__.py"
            if not fn.is_file():
                # XXX this might be a namespace
                logger.debug("No file: %s/%s", f, func)
                continue
        logger.debug("Found2 %s %s", x, f)
        yield (x, f)


def load_subgroup(
    _fn=None,
    prefix=None,
    sub_pre=None,
    sub_post=None,
    ext_pre=None,
    ext_post=None,
    **kw,
):
    """
    A decorator like click.group, enabling loading of subcommands

    Internal extensions are loaded as ``{sub_pre}.*.{sub_post}``.
    External extensions are loaded as ``{ext_pre}.*.{ext_post}``.

    All other arguments are forwarded to `click.command`.
    """

    def _ext(fn, **kw):
        return click.command(**kw)(fn)

    kw["cls"] = partial(
        kw.get("cls", Loader),
        _util_sub_pre=sub_pre or this_load.get() or prefix,
        _util_sub_post=sub_post or (None if prefix is None else "cli"),
        _util_ext_pre=ext_pre or prefix,
        _util_ext_post=ext_post or (None if prefix is None else "_main.cli"),
    )

    if _fn is None:
        return partial(_ext, **kw)
    else:
        return _ext(_fn, **kw)


class Loader(click.Group):
    """
    A `click.group` that loads additional commands from subfolders and/or extensions.

    Subfolders: set _util_sub_pre to your module's name.
        This works with namespace packages.
        E.g. "distkv.command" loads "distkv.command.*.cli".

    Extensions: set _util_ext_pre to the extension basename.
        Set _util_ext_post to the name of the extension.

        E.g. "distkv_ext"+"client" loads "distkv_ext.*.client.cli".

    Both work in parallel.

    Caller:

        from moat.util import Loader
        from functools import partial

        @click.command(cls=partial(Loader,_util_sub_post='command'))
        async def cmd()
            print("I am the main program")

    Sub-Command Usage (``main`` is defined for you), e.g. in ``command/subcmd.py``::

        from moat.util import Loader
        from functools import partial

        @main.command / group()
        async def cmd(self):
            print("I am", self.name)  # prints "subcmd"
    """

    # ruff:noqa:SLF001

    def __init__(
        self,
        *,
        _util_sub_pre=None,
        _util_sub_post=None,
        _util_ext_pre=None,
        _util_ext_post=None,
        **kw,
    ):
        logger.debug(
            "* Load: %s.*.%s / %s.*.%s",
            _util_sub_pre,
            _util_sub_post,
            _util_ext_pre,
            _util_ext_post,
        )
        if _util_sub_pre is not None:
            self._util_sub_pre = _util_sub_pre
        if _util_sub_post is not None:
            self._util_sub_post = _util_sub_post
        if _util_ext_pre is not None:
            self._util_ext_pre = _util_ext_pre
        if _util_ext_post is not None:
            self._util_ext_post = _util_ext_post
        super().__init__(**kw)

    def get_sub_ext(self, ctx):
        """Fetch extension variables"""
        sub_pre = getattr(
            # pylint: disable=protected-access
            self,
            "_util_sub_pre",
            ctx.obj._util_sub_pre,
        )
        sub_post = getattr(
            # pylint: disable=protected-access
            self,
            "_util_sub_post",
            ctx.obj._util_sub_post,
        )
        ext_pre = getattr(
            # pylint: disable=protected-access
            self,
            "_util_ext_pre",
            ctx.obj._util_ext_pre,
        )
        ext_post = getattr(
            # pylint: disable=protected-access
            self,
            "_util_ext_post",
            ctx.obj._util_ext_post,
        )

        if sub_pre is None:
            sub_post = None
        elif sub_post is None:
            sub_pre = ("cli",)
        elif isinstance(sub_post, str):
            sub_post = sub_post.split(".")

        if ext_pre is None:
            ext_post = None
        elif ext_post is None:
            ext_pre = None
        elif isinstance(ext_post, str):
            ext_post = ext_post.split(".")
            if len(ext_post) == 1:
                ext_post.append("cli")

        return sub_pre, sub_post, ext_pre, ext_post

    def list_commands(self, ctx):
        "show subpackages"
        rv = super().list_commands(ctx)
        sub_pre, sub_post, ext_pre, ext_post = self.get_sub_ext(ctx)
        logger.debug("* List: %s.*.%s / %s.*.%s", sub_pre, sub_post, ext_pre, ext_post)

        if sub_pre:
            for _finder, name, _ispkg in _namespaces(sub_pre):
                # ruff:noqa:PLW2901 # var overwritten
                logger.debug("Sub %s", name)
                name = name.rsplit(".", 1)[1]
                if name[0] == "_":
                    continue
                if load_ext(sub_pre, name, *sub_post):
                    rv.append(name)

        if ext_pre:
            for n, _ in list_ext(ext_pre):
                logger.debug("Ext %s", n)
                rv.append(n)
        rv.sort()
        logger.debug("List: %r", rv)
        return rv

    def get_command(self, ctx, cmd_name):
        "add subpackages"
        command = super().get_command(ctx, cmd_name)

        sub_pre, sub_post, ext_pre, ext_post = self.get_sub_ext(ctx)

        if command is None and ext_pre is not None:
            command = load_ext(ext_pre, cmd_name, *ext_post)
            if command is not None:
                cf = load_cfg(f"{ext_pre}.{cmd_name}")
                merge(ctx.obj.cfg, cf, replace=False)

        if command is None:
            if sub_pre is None:
                return None
            command = load_ext(sub_pre, cmd_name, *sub_post)
            if command is not None:
                cf = load_cfg(f"{sub_pre}.{cmd_name}")
                merge(ctx.obj.cfg, cf, replace=False)

        if command is None:
            # raise click.UsageError(f"No such subcommand: {cmd_name}")
            return None
        command.__name__ = command.name = cmd_name
        return command


class MainLoader(Loader):
    """
    A special loader that runs the main setup code even if there's a
    subcommand with "--help".
    """

    async def invoke(self, ctx):
        if not getattr(ctx, "_moat_invoked", False):
            await ctx.invoke(self.callback, **ctx.params)
        return await super().invoke(ctx)


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
    cls=MainLoader,
    add_help_option=False,
    invoke_without_command=True,
)  # , __file__, "command"))
@click.option("-V", "--verbose", count=True, help="Be more verbose. Can be used multiple times.")
@click.option("-L", "--debug-loader", is_flag=True, help="Debug submodule loading.")
@click.option("-Q", "--quiet", count=True, help="Be less verbose. Opposite of '--verbose'.")
@click.option("-D", "--debug", count=True, help="Enable debug speed-ups (smaller keys etc).")
@click.option(
    "-l",
    "--log",
    multiple=True,
    help="Adjust log level. Example: '--log asyncactor=DEBUG'.",
)
@click.option(
    "-c",
    "--cfg",
    type=click.Path("r"),
    default=None,
    help="Configuration file (YAML).",
    multiple=True,
)
@click.option(
    "-h",
    "-?",
    "--help",
    is_flag=True,
    help="Show help. Subcommands only understand '--help'.",
)
@attr_args(par_name="Config item")
@click.pass_context
async def main_(ctx, verbose, quiet, help=False, **kv):  # pylint: disable=redefined-builtin
    """
    This is the main command. (You might want to override this text.)

    You need to add a subcommand for this to do anything.
    """
    ctx.allow_interspersed_args = True

    # The above `MainLoader.invoke` call causes this code to be called
    # twice instead of never.
    if hasattr(ctx, "_moat_invoked"):
        return
    ctx._moat_invoked = True  # pylint: disable=protected-access
    wrap_main(ctx=ctx, verbose=max(0, 1 + verbose - quiet), **kv)
    if help or ctx.invoked_subcommand is None and not ctx.protected_args:
        print(ctx.get_help())
        ctx.exit()


def wrap_main(  # pylint: disable=redefined-builtin,inconsistent-return-statements
    main=main_,
    *,
    vars_=(),
    eval_=(),
    path_=(),
    proxy_=(),
    name=None,
    sub_pre=None,
    sub_post=None,
    ext_pre=None,
    ext_post=None,
    cfg=None,
    CFG=None,
    args=None,
    wrap=False,
    verbose=1,
    debug=0,
    debug_loader=False,
    log=(),
    ctx=None,
    help=None,
) -> Awaitable:
    """
    The main command entry point, when testing.

    main: special main function, defaults to moat.util.main_
    name: command name, defaults to {main}'s toplevel module name.
    {sub,ext}_{pre,post}: commands to load in submodules or extensions.

    cfg: configuration file(s), default: various locations based on {name}, False=don't load
    CFG: default configuration (dir or file), relative to caller
         Default: load from name._config

    wrap: Flag: this is a subcommand. Don't set up logging, return the awaitable.
    args: Argument list if called from a test, `None` otherwise.
    help: Help text of your code.

    Internal extensions are loaded as ``{sub_pre}.*.{sub_post}``.
    External extensions are loaded as ``{ext_pre}.*.{ext_post}``.

    cfg.moat may contain values for {sub,ext}_{pre,post}.
    """

    obj = getattr(ctx, "obj", None)
    if obj is None:
        obj = attrdict()

    opts = obj.get("moat", None)
    if opts is None:
        obj.moat = opts = attrdict()

    if sub_pre is None:
        sub_pre = opts.get("sub_pre", None)
    else:
        opts["sub_pre"] = sub_pre

    if sub_post is None:
        sub_post = opts.get("sub_post", None)
    else:
        opts["sub_post"] = sub_post

    if ext_pre is None:
        ext_pre = opts.get("ext_pre", None)
    else:
        opts["ext_pre"] = ext_pre

    if ext_post is None:
        ext_post = opts.get("ext_post", None)
    else:
        opts["ext_post"] = ext_post

    if name is None:
        name = opts.get("name", "moat")
    else:
        opts["name"] = name

    if sub_pre is True:
        import inspect  # pylint: disable=import-outside-toplevel

        sub_pre = inspect.currentframe().f_back.f_globals["__package__"]
    elif sub_pre is None:
        sub_pre = name
    if sub_post is None:
        sub_post = "_main.cli"

    if main is None:
        if help is not None:
            raise RuntimeError("You can't set the help text this way")
    else:
        main.context_settings["obj"] = obj
        if help is not None:
            main.help = help

    obj._util_sub_pre = sub_pre  # pylint: disable=protected-access
    obj._util_sub_post = sub_post  # pylint: disable=protected-access
    obj._util_ext_pre = ext_pre  # pylint: disable=protected-access
    obj._util_ext_post = ext_post  # pylint: disable=protected-access

    if CFG is None:
        CFG = opts.get("CFG")

    if isinstance(CFG, str):
        p = FSPath(CFG)
        if not p.is_absolute():
            p = FSPath((main or main_).__file__).parent / p
        with open(p) as cfgf:
            CFG = yload(cfgf, attr=True)
    elif CFG is None:
        CFG = obj.get("CFG", None)
        if CFG is None:
            CFG = load_cfg(name)

    obj.stdout = CFG.get("_stdout", sys.stdout)  # used for testing
    obj.CFG = CFG

    if not cfg:
        cfg = to_attrdict(read_cfg(name, None))
    elif isinstance(cfg, (list, tuple)):
        cf = {}
        for fn in cfg:
            merge(cf, read_cfg(name, fn), replace=True)
        cfg = to_attrdict(cf)
    else:
        cfg = to_attrdict(read_cfg(name, cfg))

    if cfg:
        merge(cfg, obj.CFG, replace=False)
    else:
        cfg = CFG
    obj.cfg = cfg = to_attrdict(cfg)

    obj.debug = verbose
    obj.DEBUG = debug

    obj.cfg = process_args(obj.cfg, vars_=vars_, eval_=eval_, path_=path_, proxy_=proxy_)

    if wrap:
        pass
    elif hasattr(logging.root, "_MoaT"):
        logging.debug("Logging already set up")
    else:
        # Configure logging. This is a somewhat arcane art.
        lcfg = obj.cfg.setdefault("logging", {})
        lcfg.setdefault("version", 1)
        lcfg.setdefault("root", {})["level"] = (
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
        logging.config.dictConfig(lcfg)

        logging.basicConfig = _no_config
        logging.config.dictConfig = _no_config
        logging.config.fileConfig = _no_config

        logging.captureWarnings(verbose > 0)
        logger.disabled = False
        if debug_loader:
            logger.level = logging.DEBUG
            for p in sys.path:
                logger.debug("Path: %s", p)
        logging.root._MoaT = True

    obj.logger = logging.getLogger(name)

    try:
        # pylint: disable=no-value-for-parameter,unexpected-keyword-arg
        # NOTE this return an awaitable
        if ctx is not None:
            ctx.obj = obj
        elif main is not None:
            if wrap:
                main = main.main
            with ungroup():
                return main(args=args, standalone_mode=False, obj=obj)

    except click.exceptions.MissingParameter as exc:
        print(
            f"You need to provide an argument {exc.param.name.upper()!r}.\n",
            file=sys.stderr,
        )
        print(exc.cmd.get_help(exc.ctx), file=sys.stderr)
        sys.exit(2)
    except click.exceptions.UsageError as exc:
        try:
            s = str(exc)
        except TypeError:
            logger.exception("??", exc_info=exc)
        else:
            print(s, file=sys.stderr)
        sys.exit(2)
    except click.exceptions.Abort:
        print("Aborted.", file=sys.stderr)
