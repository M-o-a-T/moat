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


## Command Structure Conventions

Several MoaT commands deal with non-trivial data structures. We need to
establish a common way of handling access to these.

### Simple Elements at path

Example: `moat link data PATH ...`. This command acts on a single data item.

Here, not using a path is pointless.

### Complex elements at path

Example: `moat link flow at PATH ...`. While command also acts on a single data item,
there are other commands (check data below a path, find the flow definition applicable
to an item, …) that don't need one.

### Prefix plus Path

Example: `moat link metrics NAME at PATH ...`. Here there are (possibly)
several services, with data hierarchies below them.

Using `-` as the name lists available servers.

## Commonly-used arguments

### `-s`, `--set`

Specifying typed arguments to MoaT methods or data structures can be a
tedious business. This argument, which can be used multiple times, tries
to make the process somewhat less tedious.

`--set` takes two arguments.

The first is the path to the datum to be added or
changed *within* the affected data structure; if you want to set the
data structure itself, use `:`. A *null* path element (`:n`) selects the
end of an array. If it is the first element, it is also used to select
the list of positional parameters. `+` is a shortcut for `:n:n`; if you
really do want to access a key that's named `+`, use `:=`.

The second is the actual datum, interpreted as float/integer/string
depending on parsability. A couple of prefix characters are available to
disambiguate:

* `~str`: always string
* `=value`: evaluated. Special names:
  * `=-`: `NotGiven`: delete this.
  * `=t`: `True`
  * `=f`: `False`
  * `=n`: `None`
* `.path`: a path. The leading dot is stripped.
* `:path`: also a path; the colon is not stripped.
  Used as a convenience: `:42.answer` is the same as `.:42.answer`.
* `^proxy`: a named proxy. Rarely used.
