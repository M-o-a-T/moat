from __future__ import annotations
import os
import anyio
from functools import partial
from asyncowfs.mock import some_server
from moat.util import ensure_cfg

from .task import task
import contextlib

PORT = ((os.getpid() + 101) % 9999) + 40000


async def server(client, tree={}, options={}, evt=None):  # pylint: disable=dangerous-default-value
    async with anyio.create_task_group() as tg:
        listener = await anyio.create_tcp_listener(
            local_host="127.0.0.1",
            local_port=PORT,
            reuse_port=True,
        )

        async def may_close():
            with contextlib.suppress(anyio.ClosedResourceError, anyio.BrokenResourceError):
                await listener.serve(partial(some_server, tree, options))

        addr = listener.extra(anyio.abc.SocketAttribute.raw_socket).getsockname()
        tg.start_soon(may_close)

        cfg = {"kv": client._cfg}
        ensure_cfg("moat.kv.ow", cfg)

        await client.set(
            client._cfg.ow.prefix + ("server", "127.0.0.1"),
            value=dict(server=dict(host="127.0.0.1", port=addr[1])),
        )

        await task(client, client._cfg, "127.0.0.1", evt)
