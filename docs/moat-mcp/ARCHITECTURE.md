# Architecture — moat.mcp

Generic **Model Context Protocol** server running over stdio, exposing MoaT
subsystems as MCP tools to AI clients (`__init__.py:4-12`).

## Key types

- **`Service`** (`__init__.py:38`) — base class. Subclasses connect to a
  subsystem, implement `register(mcp)` to add tools (prefixed with
  `self.name`), and use `_ctx()` (via `CtxObj`) for setup/teardown.
- **`services(cfg, tg)`** (`__init__.py:96`) — factory/context manager
  instantiating all configured services from `cfg.services` via
  `load_service()`.
- **`load_service(name)`** (`__init__.py:79`) — looks up the `Service` class
  in module `moat.mcp.<name>` via `moat.lib.run.load_ext`.
- **`LinkService` / `LinkMCP` / `Watch`** (`link.py`) — the sole concrete
  service. Connects to a `moat.link.client.Link` and exposes five tools:
  `link_get_value`, `link_set_value`, `link_watch_start`, `link_watch_get`,
  `link_watch_stop`. Background tasks feed change notifications into
  per-watch queues.

## Entry point

`_main.py` defines `moat mcp stdio` → calls `_server.py:run()`, which creates
a `FastMCP` server, enters all services, registers their tools, and calls
`mcp.run_stdio_async()`.

## Config

`_cfg.yaml` declares `services: { link: {} }`.

## Integration

Depends on `moat.util` (`CtxObj`, `NotGiven`), `moat.lib.run` (`load_ext`),
`moat.lib.config` (`CFG`), `moat.lib.path` (`P`, `Path`), and
`moat.link.client` (`Link`). The external `mcp` package
(`mcp.server.fastmcp.FastMCP`) is **isolated in `_server.py`** to keep the
type-checked core clean (and is excluded from `tool.ty.src` in
`pyproject.toml`).
