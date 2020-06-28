"""
Akumuli task for DistKV
"""

import anyio
import asyncakumuli as akumuli
import socket
try:
    from collections.abc import Mapping
except ImportError:
    from collections import Mapping

from distkv.util import combine_dict, NotGiven, attrdict
from distkv.exceptions import ClientConnectionError
from distkv_ext.akumuli.model import AkumuliRoot, AkumuliServer

import logging
logger = logging.getLogger(__name__)

async def task(client, cfg, server: AkumuliServer, evt=None):
    cfg = combine_dict(server.value_or({}, Mapping).get('server',{}), 
                       server.parent.value_or({}, Mapping).get('server',{}), 
                       cfg['server_default'])

    try:
        async with anyio.create_task_group() as tg:
            async with akumuli.connect(tg, **cfg) as srv:
                await server.set_server(srv)
                if evt is not None:
                    await evt.set()

                while True:
                    await anyio.sleep(99999)
    except TimeoutError:
        raise
    except socket.error as e:  # this would eat TimeoutError
        raise ClientConnectionError(cfg['host'], cfg['port']) from e

