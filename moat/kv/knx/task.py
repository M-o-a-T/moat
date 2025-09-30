"""
KNX task for MoaT-KV
"""

from __future__ import annotations

import anyio

import xknx
from xknx.io import ConnectionConfig, ConnectionType

try:
    from collections.abc import Mapping
except ImportError:
    from collections.abc import Mapping

import logging

from moat.util import combine_dict
from moat.kv.exceptions import ClientConnectionError

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model import KNXserver

logger = logging.getLogger(__name__)


async def task(client, cfg, server: KNXserver, evt=None, local_ip=None, initial=False):  # noqa:D103
    client  # noqa:B018
    cfg = combine_dict(server.value_or({}, Mapping), cfg["server_default"])
    add = {}
    if local_ip is not None:
        add["local_ip"] = local_ip

    try:
        ccfg = ConnectionConfig(
            connection_type=ConnectionType.TUNNELING,
            gateway_ip=cfg["host"],
            gateway_port=cfg.get("port", 3671),
            **add,
        )
        async with xknx.XKNX().run(connection_config=ccfg) as srv:
            await server.set_server(srv, initial=initial)
            if evt is not None:
                evt.set()

            await anyio.sleep_forever()
    except TimeoutError:
        raise
    except OSError as e:  # this would eat TimeoutError
        raise ClientConnectionError(cfg["host"], cfg["port"]) from e
