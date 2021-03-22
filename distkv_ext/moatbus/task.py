from __future__ import annotations

"""
Gateway task for DistKV/MoaT
"""

import typing

if typing.TYPE_CHECKING:
    from .model import MOATconn


async def gateway(conn: MOATconn, prefix="abc123"):
    """
    Gate between the DistKV tunnel and an external bus.

    TODO more than one
    """

    async def serial2mqtt():
        async for msg in conn:
            data={k:getattr(msg,k) for k in msg._attrs}
            data['_id'] = client.name
            await self.mqtt.send(msg)

    async def mqtt2serial():
        async with client.msg_monitor(topic=self.parent.topic) as mon:
            async for msg in mon:
                if msg.get('_id','') == client.name:
                    continue
                try:
                    await conn.send(msg)
                except TypeError:
                    logger.exception("Owch: %r", msg)

    client = conn.root.client

    async with conn.backend as conn:
        async with anyio.create_task_group() as n:
            await n.spawn(serial2mqtt)
            await n.spawn(mqtt2serial)


