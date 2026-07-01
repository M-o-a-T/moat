# MCP server

% start synopsis
% start main

An MCP (Model Context Protocol) server for MoaT.

This package provides a stdio MCP server that exposes MoaT subsystems to MCP
clients. Each subsystem is implemented as a *service* in a
`moat.mcp.<name>` submodule; the enabled services are listed in the
`moat.mcp.services` configuration.

% end synopsis

## Services

The initial service is `link`, which exposes a connected MoaT-Link instance.
Its tools are:

* `link_get_value` – read the value stored at a path.
* `link_set_value` – store a value at a path.
* `link_watch_start` – start watching a path (optionally a subtree).
* `link_watch_get` – retrieve pending changes, optionally waiting for the first.
* `link_watch_stop` – stop a watch.

% end main

## Usage

Run the server with:

```
moat mcp stdio
```

The command connects every configured service and serves MCP requests on
stdin/stdout.

## License

This project is licensed under the same terms as MoaT.
