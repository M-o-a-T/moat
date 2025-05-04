"""
KNX task for MoaT-KV
"""

import anyio
import xknx
from xknx.io import ConnectionConfig, ConnectionType
import socket

try:
    from collections.abc import Mapping
except ImportError:
    from collections import Mapping

from moat.util import combine_dict
from moat.kv.exceptions import ClientConnectionError
from .model import KNXserver

import logging

logger = logging.getLogger(__name__)


async def task(
    client, cfg, server: KNXserver, evt=None, local_ip=None, initial=False
):  # pylint: disable=unused-argument
    cfg = combine_dict(server.value_or({}, Mapping), cfg["server_default"])
    add = {}
    if local_ip is not None:
        add["local_ip"] = local_ip

    try:
        ccfg = ConnectionConfig(
            connection_type=ConnectionType.TUNNELING,
            gateway_ip=cfg["host"],
            gateway_port=cfg.get("port", 3671),
            **add
        )
        async with xknx.XKNX().run(connection_config=ccfg) as srv:
            await server.set_server(srv, initial=initial)
            if evt is not None:
                evt.set()

            while True:
                await anyio.sleep(99999)
    except TimeoutError:
        raise
    except socket.error as e:  # this would eat TimeoutError
        raise ClientConnectionError(cfg["host"], cfg["port"]) from e
