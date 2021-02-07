import os
import anyio
from functools import partial
from asyncowfs.mock import some_server

from distkv_ext.owfs.task import task

PORT = ((os.getpid() + 101) % 9999) + 40000


async def server(client, tree={}, options={}, evt=None):  # pylint: disable=dangerous-default-value

    async with anyio.create_task_group() as tg:
        listener = await anyio.create_tcp_listener(
            local_host="127.0.0.1", local_port=PORT, reuse_port=True
        )

        async def may_close():
            try:
                await listener.serve(partial(some_server, tree, options))
            except (anyio.ClosedResourceError, anyio.BrokenResourceError):
                pass

        addr = listener.extra(anyio.abc.SocketAttribute.raw_socket).getsockname()
        await tg.spawn(may_close)

        await client.set(
            client._cfg.owfs.prefix + ("server", "127.0.0.1"),
            value=dict(server=dict(host="127.0.0.1", port=addr[1])),
        )

        await task(client, client._cfg, "127.0.0.1", evt)
