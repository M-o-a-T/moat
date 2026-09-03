(extending-moat-link)=
# Extending MoaT-Link

MoaT-Link comes with a built-in extension mechanism for its command line,
based on Python namespaces and import discovery.

Your extension needs to ship a `moat.link.NAME` module, with a
`_main.py` file that exports a `cli` command (used as an
`asyncclick.group`).  This adds the subcommand `NAME` to `moat link`.

## How discovery works

The `moat link` command is decorated with `@load_subgroup` (from
`moat.lib.run`), configured with:

```python
@load_subgroup(
    sub_pre="moat.link.cmd",   # internal sub-commands
    sub_post="cli",
    ext_pre="moat.link",        # external extensions
    ext_post="_main.cli",
)
```

At runtime, the `Loader` class scans two namespaces:

1. **Internal** (`moat.link.cmd.*`): modules in `moat/link/cmd/` that
   export a `cli` attribute.  These provide the built-in `data`,
   `error`, `host`, `codec`, `conv`, `raw`, and `cmd` sub-commands.

2. **External** (`moat.link.*`): packages under the `moat.link`
   namespace that export a `_main.cli` attribute.  These are the
   extension modules: `knx`, `ow`, `wago`, `cal`, `gpio`, `ha`,
   `metrics`, `notify`, `flow`, `schema`, `server`, `web`, etc.

Both work in parallel.  Unique-prefix abbreviation is supported: `moat
link da` resolves to `moat link data` if no ambiguity exists.

## Creating a new extension

1. Create `moat/link/NAME/` with at minimum:

   ```
   moat/link/NAME/
   ├── __init__.py      # config registration
   ├── _main.py         # CLI (asyncclick group)
   ├── _cfg.yaml         # default config
   ```

2. In `__init__.py`, register the config:

   ```python
   from moat.lib.config import register as _register
   _register(__name__)
   ```

3. In `_main.py`, define the CLI group:

   ```python
   import asyncclick as click
   from moat.lib.run import AliasedGroup
   from moat.link.client import Link

   @click.group(cls=AliasedGroup, short_help="Manage MyThing.")
   @click.pass_context
   async def cli(ctx):
       obj = ctx.obj
       cfg = obj.cfg["link"]
       obj.conn = await ctx.with_async_resource(Link(cfg))
       obj.my_cfg = obj.cfg.link.my_name
   ```

4. Add sub-commands to the group:

   ```python
   @cli.command("run")
   @click.argument("name", nargs=1)
   @click.pass_obj
   async def run_(obj, name):
       """Run the connector."""
       ...
   ```

5. Create packaging in `packaging/moat-link-NAME/` with `pyproject.toml`
   and `README.md`.

6. Create docs in `docs/moat-link-NAME/` with `index.md` and `api.rst`,
   and wire into the toctree in `docs/moat-link/index.md`.

7. Create tests in `tests/moat_link_NAME/`.

## Data access helpers

Extensions use `moat.link._data` for data access:

- `data_get(conn, path, ...)` — dump a subtree as YAML.
- `node_attr(obj, path, ...)` — read/modify a node's attributes.
- `res_get(res, attr)` / `res_update(res, attr, value)` — low-level
  dict helpers.

## Node tree pattern

For typed monitoring, subclass `moat.link.node.Node` and override
`add_child`:

```python
from attrs import define
from moat.link.node import Node

@define
class MyEntry(Node):
    """One entry."""

@define
class MyRoot(Node):
    def add_child(self, item):
        self._sub[item] = s = MyEntry()
        return s
```

Watch with typed tree:

```python
async with link.d_watch(path, subtree=True, mark=True, cls=MyRoot) as mon:
    async for msg in mon:
        ...
```

## Error handling

Use the `LinkSender` error methods instead of the old `ErrorRoot`:

- `link.e_exc(path, exc)` — record an exception.
- `link.e_info(path, text)` — record an informational message.
- `link.e_ok(path)` — mark an error as resolved.

## Migrating from moat.kv

See `kv-migration-guide.md` for the step-by-step checklist and API
mapping table.
