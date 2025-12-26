# MoaT and the command line

MoaT uses an async version of `click`. The `click` documentation applies
unmodified, except that you can optionally use async code wherever you
like.

## Writing your own

This is easy.

Add a file `yours.__main__.py` to your package:

```
from __future__ import annotations
from moat.main import run

async def hello(ctx: asyncclick.Context):
    print("Hello")

run(hello, doc="This is a greeting.")
```

You can now run your command with `python -myours`.

`run` wraps the standard MoaT argument handling around your code. `ctx`
is a standard :class:`asyncclick.Context` object. `ctx.obj.cfg` contains
the configuration, as specifified by the command line. By default,
the content of `/etc/moat/moat.cfg` is available.


### Subcommands

You can add subcommands via `@moat.lib.run.main_.command()`. Alternately, the
command handler can load subcommands when requested.

In `yours.__main__.py`:

```
run(hello, sub_pre="yours.cmd",sub_post="cli",
    ext_pre="yours", ext_post="_main.cli")
```

MoaT will now scan your package namespace and add all functions
`yours.cmd.XXX.cli` and `yours.XXX._main.cli` as subcommands.
The subcommand(s) will be named XXX.

The intent is for the `sub_` prefix to access built-in commands, while the
`ext_` prefix addresses commands from separate and possibly-namespaced
packages.

If you want sub-subcommands, do this in `yours.foo._main.py`:

```
import asyncclick as click
from moat.main import load_subgroup

@load_subgroup(sub_pre="yours.foo.cmd", sub_post="cli")
@click.pass_context
async def cli(ctx):
    ...
```

You can now transparently run the code in `yours.foo.bar.cli` with
`python3 -myours foo bar`.

#### Optional subcommands

You will notice that the code of a command will run regardless of whether a
subcommand is used (Click: `invoke_without_command=True`), because typical
usage is for the supercommand to set up a common context, connect to
MoaT-Link and/or a database, etc..  If you don't want that, you can use
this code to test for the presence of subcommands:

```
if ctx.invoked_subcommand is not None:
    return
```

#### Setting up a common context

```
async def hello(ctx):
    obj = ctx.obj
    cfg = obj.cfg["link"]
    obj.conn = await ctx.with_async_resource(Link(cfg))
```

You'd normally write the last line as

```
async with Link(cfg) as obj.conn:
    await run_subcommand(ctx)
```
which doesn't work with `click` because it runs subcommands
after the supercommand's code returns.
