from __future__ import annotations

"""
Gateway task for DistKV/MoaT
"""

import typing
import logging
import anyio
from moatbus.message import BusMessage

if typing.TYPE_CHECKING:
    from .model import MOATconn

async def gateway(conn: MOATconn, prefix="abc123"):
    """
    Gate between the DistKV tunnel and an external bus.

    TODO more than one
    """

    logger = logging.getLogger(f"moat.bus.{conn.parent._name}.{conn._name}")
    client = conn.root.client

    async def serial2mqtt():
        async for msg in port:
            logger.info("S: %s",msg)
            data={k:getattr(msg,k) for k in msg._attrs}
            data['_id'] = client.name
            await client.msg_send(conn.parent.topic, data)

    async def mqtt2serial():
        async with client.msg_monitor(topic=conn.parent.topic) as mon:
            async for msg in mon:
                msg = msg.data
                m_id = msg.pop('_id','')
                if m_id == client.name:
                    logger.debug("m: %s",msg)
                    continue
                logger.debug("M: %s (_id:%s)",msg,m_id)
                msg = BusMessage(**msg.data)

                try:
                    await port.send(msg)
                except TypeError:
                    logger.exception("Owch: %r", msg)

    client = conn.root.client

    async with conn.backend() as port:
        async with anyio.create_task_group() as n:
            await n.spawn(serial2mqtt, _name="s2m")
            await n.spawn(mqtt2serial, _name="m2s")


