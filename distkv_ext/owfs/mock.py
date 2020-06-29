import trio
import anyio
from functools import partial
from asyncowfs.mock import some_server

try:
    from contextlib import asynccontextmanager
except ImportError:
    from async_generator import asynccontextmanager

from distkv_ext.owfs.task import task

async def server(client, tree={}, options={}, polling=False, scan=None, initial_scan=True, evt=None):

    async with trio.open_nursery() as n:
        server = await n.start(
            partial(trio.serve_tcp, host="127.0.0.1"),
            partial(some_server, tree, options), 0
        )
        addr = server[0].socket.getsockname()

        await client.set(client._cfg.owfs.prefix+("server","127.0.0.1"), value=dict(server=dict(host="127.0.0.1",port=addr[1])))

        await task(client, client._cfg, "127.0.0.1", evt)

