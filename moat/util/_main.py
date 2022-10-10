import importlib
import logging
import os
import sys
from collections import defaultdict
from collections.abc import Mapping
from contextvars import ContextVar
from functools import partial
from logging.config import dictConfig
from pathlib import Path
from typing import Awaitable

import asyncclick as click

from ._dict import attrdict, combine_dict, to_attrdict
from ._impl import NotGiven
from ._msgpack import Proxy
from ._path import P, path_eval
from ._yaml import yload

logger = logging.getLogger(__name__)

__all__ = [
    "main_",
    "read_cfg",
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


def attr_args(proc=None, with_path=True, with_eval=True, with_proxy=False):
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
            help="Parameter (name value), as path",
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
            help="Parameter (name value), evaluated",
            hidden=not with_eval,
        )(proc)

        proc = click.option(
            "-v",
            "--var",
            "vars_",
            nargs=2,
            type=(P, str),
            multiple=True,
            help="Parameter (name value)",
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


def process_args(val, vars_, eval_, path_, proxy_=(), vs=None):
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
            if v == "-":
                v = NotGiven
            elif v == "/":  # pylint: disable=W0631
                if vs is None:
                    raise click.BadOptionUsage(
                        option_name=k, message="A slash value doesn't work here."
                    )
                v = NoneType
            else:
                v = path_eval(v)  # pylint: disable=W0631
            yield k, v
        for k, v in path_:
            v = P(v)
            yield k, v
        for k, v in proxy_:
            v = Proxy(v)
            yield k, v

    for k, v in data():
        if not k:
            if vs is not None:
                raise click.BadOptionUsage(
                    option_name=k, message="You can't use empty paths here."
                )
            if n:
                raise click.BadOptionUsage(
                    option_name=k, message="Setting a single value conflicts."
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
                with open(path, "r") as cf:
                    cfg = yload(cf)
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
    try:
        mod = importlib.import_module(dp)
        mod = getattr(mod, attr[-1])
    except AttributeError:
        if err:
            raise
        return None
    except (ModuleNotFoundError, FileNotFoundError) as exc:
        if err:
            raise
        if (
            exc.name != dp
            and not exc.name.startswith(  # pylint: disable=no-member ## duh?
                f"{dp}._"
            )
        ):
            raise
        return None
    else:
        return mod


def _namespaces(name):
    import pkgutil  # pylint: disable=import-outside-toplevel

    try:
        ext = importlib.import_module(name)
    except ModuleNotFoundError:
        return ()
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
        f = Path(finder.path) / x
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
        if (f / ".no_load").is_file():
            continue
        fn = f / (func + ".py")
        if not fn.is_file():
            fn = f / func / "__init__.py"
            if not fn.is_file():
                # XXX this might be a namespace
                continue
        yield (x, f)


def load_subgroup(_fn=None, sub_pre=None, sub_post=None, ext_pre=None, ext_post=None, **kw):
    """
    A decorator like click.group, enabling loading of subcommands

    ext: extensions' namespaces, default to "{name}.ext"
    plugin: submodule to load CLI from.
    sub: load *.cli() from this package, default=caller if True

    Internal extensions are loaded as ``{sub}.*.cli``.
    External extensions are loaded as ``{ext}.*.{plugin}.cli``.

    All other arguments are forwarded to `click.command`.
    """

    def _ext(fn, **kw):
        return click.command(**kw)(fn)

    kw["cls"] = partial(kw.get("cls", Loader), _util_sub_pre=sub_pre or this_load.get(), _util_sub_post=sub_post, _util_ext_pre=ext_pre, _util_ext_post=ext_post)

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

    Extensions: set _util_ext to the extension basename.
        Set _util_plugin to the name of the extension.

        E.g. "distkv_ext"+"client" loads "distkv_ext.*.client.cli".

    Both work in parallel.

    Caller:

        from moat.util import Loader
        from functools import partial

        @click.command(cls=partial(Loader,_util_plugin='command'))
        async def cmd()
            print("I am the main program")

    Sub-Command Usage (``main`` is defined for you), e.g. in ``command/subcmd.py``::

        from moat.util import Loader
        from functools import partial

        @main.command / group()
        async def cmd(self):
            print("I am", self.name)  # prints "subcmd"
    """

    def __init__(self, *, _util_sub_pre=None, _util_sub_post=None, _util_ext_pre=None, _util_ext_post=None, **kw):
        logger.debug("Load %s.*.%s / %s.*.%s",_util_sub_pre, _util_sub_post, _util_ext_pre, _util_ext_post)
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
        sub_pre = getattr(self, "_util_sub_pre", ctx.obj._util_sub_pre)  # pylint: disable=protected-access
        sub_post = getattr(self, "_util_sub_post", ctx.obj._util_sub_post)  # pylint: disable=protected-access
        ext_pre = getattr(self, "_util_ext_pre", ctx.obj._util_ext_pre)  # pylint: disable=protected-access
        ext_post = getattr(self, "_util_ext_post", ctx.obj._util_ext_post)  # pylint: disable=protected-access

        if sub_pre is None:
            sub_post = None
        elif sub_post is None:
            sub_pre = ("cli",)
        elif isinstance(sub_post,str):
            sub_post = sub_post.split(".")

        if ext_pre is None:
            ext_post = None
        elif ext_post is None:
            ext_pre = None
        elif isinstance(ext_post,str):
            ext_post = ext_post.split(".")
            if len(ext_post) == 1:
                ext_post.append("cli")

        return sub_pre,sub_post,ext_pre,ext_post

    def list_commands(self, ctx):
        rv = super().list_commands(ctx)
        sub_pre,sub_post,ext_pre,ext_post = self.get_sub_ext(ctx)

        breakpoint()

        if sub_pre:
            for finder, name, ispkg in _namespaces(sub_pre):
                name = name.rsplit(".",1)[1]
                if load_ext(sub_pre, name, *sub_post):
                    rv.append(name)

        if ext_pre:
            for n, _ in list_ext(ext_pre):
                rv.append(n)
        rv.sort()
        return rv

    def get_command(self, ctx, cmd_name):
        command = super().get_command(ctx, cmd_name)

        sub_pre,sub_post,ext_pre,ext_post = self.get_sub_ext(ctx)

        if command is None and ext_pre is not None:
            command = load_ext(ext_pre, cmd_name, *ext_post)

        if command is None:
            if sub_pre is None:
                return None
            command = load_ext(sub_pre, cmd_name, *sub_post)

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
    sub_post="_main.cli",
    cls=MainLoader,
    add_help_option=False,
    invoke_without_command=True,
)  # , __file__, "command"))
@click.option("-v", "--verbose", count=True, help="Be more verbose. Can be used multiple times.")
@click.option("-q", "--quiet", count=True, help="Be less verbose. Opposite of '--verbose'.")
@click.option("-D", "--debug", count=True, help="Enable debug speed-ups (smaller keys etc).")
@click.option(
    "-l",
    "--log",
    multiple=True,
    help="Adjust log level. Example: '--log asyncactor=DEBUG'.",
)
@click.option("-c", "--cfg", type=click.Path("r"), default=None, help="Configuration file (YAML).")
@click.option(
    "-C",
    "--conf",
    multiple=True,
    help="Override a config entry. Example: '-C server.bind_default.port=57586'",
)
@click.option(
    "-h",
    "-?",
    "--help",
    is_flag=True,
    help="Show help. Subcommands only understand '--help'.",
)
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
    name=None,
    sub_pre=None,
    sub_post=None,
    ext_pre=None,
    ext_post=None,
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
    The main command entry point, when testing.

    main: special main function, defaults to moat.util.main_
    name: command name, defaults to {main}'s toplevel module name.
    {sub,ext}_{pre,post}: commands to load in submodules or extensions.

    conf: a list of additional config changes
    cfg: configuration file, default: various locations based on {name}, False=don't load
    CFG: default configuration (dir or file), relative to caller
         Default: try to load from name._config

    wrap: Flag: this is a subcommand. Don't set up logging, return the awaitable.
    args: Argument list if called from a test, `None` otherwise.
    help: Help text of your code.

    Internal extensions are loaded as ``{sub}.*.cli``.
    External extensions are loaded as ``{ext}.*.{plugin}.cli``.

    cfg.moat may contain values for name/ext/plugin.
    """

    obj = getattr(ctx, "obj", None)
    if obj is None:
        obj = attrdict()

    opts = obj.get("moat", None)
    if opts is None:
        obj.moat = opts = attrdict()

    if sub_pre is None:
        plugin = opts.get("sub_pre", None)
    else:
        opts["sub_pre"] = sub_pre

    if sub_post is None:
        plugin = opts.get("sub_post", None)
    else:
        opts["sub_post"] = sub_post

    if ext_pre is None:
        plugin = opts.get("ext_pre", None)
    else:
        opts["ext_pre"] = ext_pre

    if ext_post is None:
        plugin = opts.get("ext_post", None)
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
        p = Path(CFG)
        if not p.is_absolute():
            p = Path((main or main_).__file__).parent / p
        with open(p, "r") as cfgf:
            CFG = yload(cfgf)
    elif CFG is None:
        CFG = obj.get("CFG", None)
        if CFG is None:
            try:
                CFG = importlib.import_module(f"{name}._config").CFG
            except (ImportError, AttributeError):
                CFG = {}

    if sub_pre is not None:
        for finder, name, ispkg in _namespaces(sub_pre):
            name = name.rsplit(".",1)[1]
            cf = {}
            try:
                cf = combine_dict(load_ext(sub_pre, name, "_config", "CFG", err=True), CFG.get(name, {}), cls=attrdict)
            except ModuleNotFoundError:
                fn = Path(finder.path) / name / "_config.yaml"
                if fn.is_file():
                    cf = yload(fn)

            CFG[name] = combine_dict(cf, CFG.get(name, {}), cls=attrdict)

    if ext_pre is not None:
        for n, d in list_ext(ext_pre):
            cf = {}
            try:
                try:
                    cf = load_ext(ext_pre, n, "_config", "CFG", err=True)
                except ModuleNotFoundError:
                    cf = load_ext(ext_pre, n, "config", "CFG", err=True)
            except ModuleNotFoundError:
                fn = d / "_config.yaml"
                if fn.is_file():
                    cf = yload(fn)

            CFG[n] = combine_dict(cf, CFG.get(n, {}), cls=attrdict)

    obj.stdout = CFG.get("_stdout", sys.stdout)  # used for testing
    obj.CFG = to_attrdict(CFG)

    cfg = to_attrdict(read_cfg(name, cfg))
    if cfg:
        cfg = combine_dict(cfg, CFG, cls=attrdict)
    else:
        cfg = CFG
    obj.cfg = cfg = to_attrdict(cfg)

    obj.debug = verbose
    obj.DEBUG = debug

    for k in conf:
        try:
            k, v = k.split("=", 1)
        except ValueError:
            v = NotGiven
        else:
            try:
                v = path_eval(v)
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
        logger.disabled = False

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
        print(
            f"You need to provide an argument { exc.param.name.upper() !r}.\n",
            file=sys.stderr,
        )
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
