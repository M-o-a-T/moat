"""
Akumuli task for MoaT-KV
"""

from __future__ import annotations

import anyio
from pprint import pformat

import asyncakumuli as akumuli

try:
    from collections.abc import Mapping
except ImportError:
    from collections.abc import Mapping

import logging

from asyncakumuli import DS, Entry

from moat.util import combine_dict
from moat.kv.exceptions import ClientConnectionError

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import AkumuliServer

logger = logging.getLogger(__name__)


async def task(client, cfg, server: AkumuliServer, paths=(), evt=None):  # noqa:D103
    cfg = combine_dict(
        server.value_or({}, Mapping).get("server", {}),
        server.parent.value_or({}, Mapping).get("server", {}),
        cfg["server_default"],
    )

    @staticmethod
    async def process_raw():
        async with client.msg_monitor(server.topic) as mon:
            async for msg in mon:
                try:
                    msg = msg["data"]  # noqa:PLW2901
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
            srv._distkv__tg = tg  # noqa:SLF001 # used in .model
            server.set_paths(paths)
            await server.set_server(srv)
            if evt is not None:
                evt.set()

            if server.topic is not None:
                await tg.start(process_raw)
            await anyio.sleep_forever()
    except TimeoutError:
        raise
    except OSError as e:  # this would eat TimeoutError
        raise ClientConnectionError(cfg["host"], cfg["port"]) from e
