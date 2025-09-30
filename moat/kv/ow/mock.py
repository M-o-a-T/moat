from __future__ import annotations  # noqa: D100

import anyio
import contextlib
from functools import partial

from asyncowfs.mock import some_server

from moat.util import ensure_cfg

from .task import task


async def server(client, tree: dict | None = None, options: dict | None = None, evt=None):  # noqa: D103
    async with anyio.create_task_group() as tg:
        listener = await anyio.create_tcp_listener(
            local_host="127.0.0.1",
            local_port=0,
            reuse_port=True,
        )

        async def may_close():
            with contextlib.suppress(anyio.ClosedResourceError, anyio.BrokenResourceError):
                await listener.serve(partial(some_server, tree or {}, options or {}))

        addr = listener.extra(anyio.abc.SocketAttribute.raw_socket).getsockname()
        tg.start_soon(may_close)

        cfg = {"kv": client._cfg}  # noqa: SLF001
        ensure_cfg("moat.kv.ow", cfg)

        await client.set(
            client._cfg.ow.prefix + ("server", "127.0.0.1"),  # noqa: SLF001
            value=dict(server=dict(host="127.0.0.1", port=addr[1])),
        )

        await task(client, client._cfg, "127.0.0.1", evt)  # noqa: SLF001
