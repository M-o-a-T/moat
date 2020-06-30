import trio
from functools import partial
from asyncowfs.mock import some_server

from distkv_ext.owfs.task import task


async def server(client, tree={}, options={}, evt=None):  # pylint: disable=dangerous-default-value

    async with trio.open_nursery() as n:
        s = await n.start(
            partial(trio.serve_tcp, host="127.0.0.1"), partial(some_server, tree, options), 0
        )
        addr = s[0].socket.getsockname()

        await client.set(
            client._cfg.owfs.prefix + ("server", "127.0.0.1"),
            value=dict(server=dict(host="127.0.0.1", port=addr[1])),
        )

        await task(client, client._cfg, "127.0.0.1", evt)
