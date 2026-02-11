# KV-to-Link Migration Guide

This document records the patterns and lessons learned while migrating
``moat.kv.*`` modules to ``moat.link.*``, to make subsequent migrations
easier.

## Architecture overview

| Concept | moat.kv | moat.link |
|---|---|---|
| Client | `moat.kv.client.Client` | `moat.link.client.Link` / `LinkSender` |
| Read a value | `client.get(path)` | `link.d_get(path)` |
| Write a value | `client.set(path, value)` | `link.d_set(path, value)` |
| Delete | `client.delete(path)` | `link.d_set(path, NotGiven)` |
| Watch one path | `client.watch(path, …)` | `link.d_watch(path)` |
| Watch subtree | `client.watch(path, …)` with depth | `link.d_watch(path, subtree=True)` |
| Initial-state marker | `msg.get("state") == "uptodate"` | `mark=True` → yields `None` |
| Error recording | `ErrorRoot.record_error()` / `.record_working()` | `link.e_exc()` / `link.e_ok()` / `link.e_info()` |
| Service announcement | `moat.link.announce.as_service` | same (unchanged) |
| Config registration | `moat.lib.config.register` | same (unchanged) |

## Replacing ClientRoot / ClientEntry

The ``moat.kv.obj`` module provides ``ClientRoot`` and ``ClientEntry``, a
tree of objects that automatically mirrors a KV subtree and creates typed
children.  moat.link uses a simpler model.

### The Node tree

``moat.link.node.Node`` is an attrs-based tree node.  To get typed children:

1. Subclass ``Node``.
2. Override ``add_child(self, item)`` to return the correct subclass.
3. Pass your root class as ``cls=MyRoot`` to ``link.d_watch(…, cls=…)``.

Example (from ``moat.link.metrics``):

```python
@define
class MetricsEntry(Node):
    """One series mapping."""
    ...

@define
class MetricsServer(Node):
    def add_child(self, item):
        self._sub[item] = s = MetricsEntry()
        return s

@define
class MetricsRoot(Node):
    def add_child(self, item):
        self._sub[item] = s = MetricsServer()
        return s
```

Then watch with:

```python
async with link.d_watch(path, subtree=True, mark=True, cls=MetricsRoot) as mon:
    async for msg in mon:
        ...
```

### Data access

``Node.data_`` returns the raw stored data (or ``NotGiven``).  Use
properties on your subclass to extract typed fields:

```python
@property
def source(self):
    d = self.data_
    if d is NotGiven or not isinstance(d, dict):
        return None
    return d.get("source")
```

### Reacting to changes

``Node.set_(path, data, meta)`` is called when data changes.  Override it
to trigger side effects (restart workers, update caches, etc.).

## Error handling

| Old pattern | New pattern |
|---|---|
| `err.record_error("name", subpath, message=…)` | `link.e_exc(path, exc)` or `link.e_info(path, text)` |
| `err.record_working("name", subpath)` | `link.e_ok(path)` |
| `ErrorRoot.as_handler(client)` | not needed; methods are on `LinkSender` |

## CLI migration

| Old | New |
|---|---|
| `moat.kv.obj.command.std_command` | plain ``asyncclick`` groups |
| `moat.kv.data.data_get` | `moat.link._data.data_get` |
| `moat.kv.data.node_attr` | `moat.link._data.node_attr` |
| `obj.client` (KV client) | `obj.conn` (Link instance) |

The old ``std_command`` helper auto-generates server/entry sub-commands.
In moat.link, write explicit ``@click.group`` / ``@click.command`` functions
instead — the result is more readable.

## Raw MQTT monitoring

The old code often had a ``process_raw`` function that subscribed to a raw
MQTT topic and forwarded messages.  In moat.link, data flows through the
Link layer, not raw MQTT.  Remove this feature; if raw MQTT is needed, use
``link.monitor(topic)`` from the backend.

## Packaging

- Source lives in ``moat/link/SUBMOD/``.
- Packaging in ``packaging/moat-link-SUBMOD/``.
- Docs in ``docs/moat-link-SUBMOD/``.
- Tests in ``tests/moat_link_SUBMOD/``.
- Add a ``systemd/`` directory under the packaging dir for service files.
- Add the new package to the Link toctree in ``docs/moat-link/index.md``.
- Add a synopsis entry in ``docs/index.md``.
- Mark the old ``moat-kv-*`` README as deprecated.

## Checklist for migrating ``moat.kv.FOO``

1. Create ``moat/link/FOO/`` with ``__init__.py``, ``_cfg.yaml``, model,
   task, worker, and CLI modules.
2. Subclass ``Node`` with ``add_child`` overrides for typed children.
3. Use ``d_watch(…, subtree=True, mark=True, cls=…)`` for tree monitoring.
4. Replace ``ErrorRoot`` calls with ``link.e_*`` methods.
5. Replace ``std_command`` with explicit asyncclick groups.
6. Remove raw MQTT monitoring.
7. Create packaging (pyproject.toml, Debian, systemd, Makefile).
8. Create docs (index.md, api.rst) and wire into toctrees.
9. Write tests using the existing mock infrastructure.
10. Deprecate the old package in its README.
