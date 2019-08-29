"""
WAGO task for DistKV
"""

import anyio
import wago
import socket
from collections import Mapping

from distkv.util import combine_dict, NotGiven
from distkv.exceptions import ClientConnectionError
from distkv_ext.wago.model import WAGOroot, WAGOserver

import logging
logger = logging.getLogger(__name__)

async def task(client, cfg, server: WAGOserver, evt=None):
    cfg = combine_dict(server.value_or({}, Mapping).get('server',{}), cfg['server_default'])

    try:
        async with wago.open_server(**cfg) as srv:
            await server.update_server(srv)
            if evt is not None:
                await evt.set()

            while True:
                await anyio.sleep(99999)
    except socket.error as e:
        raise ClientConnectionError(server['host'], server['port']) from e

    

