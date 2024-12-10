"""
WAGO task for MoaT-KV
"""

import anyio
import asyncwago as wago
import socket

try:
    from collections.abc import Mapping
except ImportError:
    from collections import Mapping

from moat.util import combine_dict, attrdict
from moat.kv.exceptions import ClientConnectionError
from .model import WAGOserver

import logging

logger = logging.getLogger(__name__)


async def task(client, cfg, server: WAGOserver, evt=None):
    cfg = combine_dict(server.value_or({}, Mapping).get("server", {}), cfg["server_default"])

    async def present(s, p):
        # Set the "present" attribute
        if s.val_d(None, "present") is not p:
            await s.update(s.value_or(attrdict(), Mapping)._update(["present"], value=p))

    async def merge_ports(s_card, r):
        r = set(range(1, r + 1))
        for k in r:
            try:
                s_port = s_card[k]
            except KeyError:
                s_port = s_card.allocate(k)
            await present(s_port, True)

        for s_port in s_card:
            if s_port._name not in r:
                await present(s_port, False)

    async def merge_cards(s_type, r):
        for k, v in r.items():
            try:
                s_card = s_type[k]
            except KeyError:
                s_card = s_type.allocate(k)
            await present(s_card, True)
            await merge_ports(s_card, v)

        for s_card in s_type:
            if s_card._name not in r:
                await present(s_card, False)

    async def merge_types(server, r):
        for k, v in r.items():
            try:
                s_type = server[k]
            except KeyError:
                s_type = server.allocate(k)
            await present(s_type, True)
            await merge_cards(s_type, v)

        for s_type in server:
            if s_type._name not in r:
                await present(s_type, False)

    try:
        async with wago.open_server(**cfg) as srv:
            r = await srv.describe()
            await merge_types(server, r)
            await server.set_server(srv)
            if evt is not None:
                evt.set()

            while True:
                await anyio.sleep(99999)
    except TimeoutError:
        raise
    except socket.error as e:  # this would eat TimeoutError
        raise ClientConnectionError(cfg["host"], cfg["port"]) from e
