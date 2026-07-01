(moat-mcp)=
# MCP Server

```{include} ../../packaging/moat-mcp/README.md
:start-after: % start main
:end-before: % end main
```

## Manual

`moat-mcp` adds the `moat mcp` command group.

`moat mcp stdio` connects every configured service and serves the
[Model Context Protocol](https://modelcontextprotocol.io) on stdin/stdout.

Services live in ``moat.mcp.<name>`` submodules and are enabled via the
``moat.mcp.services`` configuration mapping. The initial service is
``link``, which exposes value get/set and path-watching tools of a
connected MoaT-Link instance.

```{toctree}
:maxdepth: 2
:hidden:

api
```
