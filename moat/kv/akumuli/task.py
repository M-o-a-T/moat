"""
Akumuli task for MoaT-KV
"""

from __future__ import annotations

import anyio
import asyncakumuli as akumuli
from pprint import pformat

try:
    from collections.abc import Mapping
except ImportError:
    from collections.abc import Mapping

from moat.util import combine_dict
from moat.kv.exceptions import ClientConnectionError

from asyncakumuli import Entry, DS

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import AkumuliServer

logger = logging.getLogger(__name__)


async def task(client, cfg, server: AkumuliServer, paths=(), evt=None):  # pylint: disable=unused-argument
    cfg = combine_dict(
        server.value_or({}, Mapping).get("server", {}),
        server.parent.value_or({}, Mapping).get("server", {}),
        cfg["server_default"],
    )

    async def process_raw(self):
        async with client.msg_monitor(server.topic) as mon:
            async for msg in mon:
                try:
                    msg = msg["data"]
                except KeyError:
                    continue
                try:
                    msg.setdefault("mode", DS.gauge)
                    tags = msg.setdefault("tags", {})
                    for k, v in tags.items():
                        if isinstance(str, bytes):
                            tags[k] = v.decode("utf-8")
                        else:
                            tags[k] = str(v)
                            # no-op if it's already a string

                    e = Entry(**msg)
                    await srv.put(e)
                except Exception:
                    logger.exception("Bad message on %s: \n%s", server.topic, pformat(msg))

    try:
        async with (
            anyio.create_task_group() as tg,
            akumuli.connect(**cfg) as srv,
        ):
            srv._distkv__tg = tg
            server.set_paths(paths)
            await server.set_server(srv)
            if evt is not None:
                evt.set()

            if server.topic is not None:
                await tg.start(process_raw)
            while True:
                await anyio.sleep(99999)
    except TimeoutError:
        raise
    except OSError as e:  # this would eat TimeoutError
        raise ClientConnectionError(cfg["host"], cfg["port"]) from e
