# Copyright (c) 2015 Nicolas JOUANIN
#
# See the file license.txt for copying permission.
from __future__ import annotations

import anyio

from .broker import Broker

try:
    from moat.kv.client import client_scope as moat_kv_client_scope
    from moat.kv.errors import ErrorRoot
    from moat.util import NotGiven, PathLongener
except ImportError:
    pass


class MoatKVbroker(Broker):
    """
    A Broker that routes messages through MoaT-KV / MQTT.
    """

    __slots__ = (
        "_moat_kv_broker__client",
        "_moat_kv_broker__topic",
        "_moat_kv_broker__tranparent",
        "_moat_kv_broker__base",
    )

    def __init__(self, tg: anyio.abc.TaskGroup, config=None, plugin_namespace=None):
        self.__client = None
        super().__init__(tg, config=config, plugin_namespace=plugin_namespace)
        cfg = self.config["kv"]

        def spl(x, from_cfg=True):
            if from_cfg:
                x = cfg[x]
            if isinstance(x, str):
                x = x.split("/")
            return tuple(x)

        self.__topic = spl("topic")
        self.__base = spl("base")
        self.__transparent = [spl(x, False) for x in cfg.get("transparent", ())]

        if self.__topic[: len(self.__base)] == self.__base:
            raise ValueError("'topic' must not start with 'base'")

    async def __read_encap(self, client, cfg: dict, evt: anyio.abc.Event | None = None):  # pylint: disable=unused-argument
        """
        Read encapsulated messages from the real server and forward them
        """

        async with self.__client.msg_monitor(self.__topic) as q:
            if evt is not None:
                evt.set()
            async for m in q:
                d = m.data
                sess = d.pop("session", None)
                if sess is not None:
                    sess = self._sessions.get(sess, None)
                    if sess is not None:
                        sess = sess[0]
                await super().broadcast_message(session=sess, **d)

    async def __read_topic(self, topic, client, cfg: dict, evt: anyio.abc.Event | None = None):  # pylint: disable=unused-argument
        """
        Read topical messages from the real server and forward them
        """
        async with self.__client.msg_monitor(topic, raw=True) as q:
            if evt is not None:
                evt.set()
            async for m in q:
                d = m.raw
                t = m.topic
                await super().broadcast_message(topic=t, data=d, session=None)

    async def __session(self, cfg: dict, evt: anyio.abc.Event | None = None):
        """
        Connect to the real server, read messages, forward them
        """
        try:
            self.__client = client = await moat_kv_client_scope(**cfg)
            async with anyio.create_task_group() as tg:

                async def start(p, *a):
                    evt = anyio.Event()
                    tg.start_soon(p, *a, client, cfg, evt)
                    await evt.wait()

                if self.__topic:
                    await start(self.__read_encap)
                for t in self.__transparent:
                    await start(self.__read_topic, t)
                    await start(self.__read_topic, t + ("#",))

                if evt is not None:
                    evt.set()
                # The taskgroup waits for it all to finish, i.e. indefinitely
        finally:
            self.__client = None

    async def __retain_reader(self, cfg: dict, evt: anyio.abc.Event | None = None):  # pylint: disable=unused-argument
        """
        Read changes from MoaT-KV and broadcast them
        """

        pl = PathLongener(self.__base)
        err = await ErrorRoot.as_handler(self.__client)
        async with self.__client.watch(self.__base, fetch=True, long_path=False) as w:
            evt.set()
            async for msg in w:
                if "path" not in msg:
                    continue
                pl(msg)
                data = msg.get("value", b"")
                if not isinstance(data, (bytes, bytearray)):
                    await err.record_error(
                        "moat.mqtt",
                        msg.path,
                        data={"data": data},
                        message="non-binary data",
                    )
                    continue
                await super().broadcast_message(
                    session=None,
                    topic="/".join(msg["path"]),
                    data=data,
                    retain=True,
                )
                await err.record_working("moat.mqtt", msg.path)

    async def start(self):
        cfg = self.config["kv"]

        await super().start()

        evt = anyio.Event()
        self._tg.start_soon(self.__session, cfg, evt)
        await evt.wait()

        evt = anyio.Event()
        self._tg.start_soon(self.__retain_reader, cfg, evt)
        await evt.wait()

    async def broadcast_message(
        self,
        session,
        topic,
        data,
        force_qos=None,
        qos=None,
        retain=False,
    ):
        if isinstance(topic, str):
            ts = tuple(topic.split("/"))
        else:
            ts = tuple(topic)
            topic = "/".join(ts)

        if self.__client is None:
            self.logger.error("No client, dropping %s", topic)
            return  # can't do anything

        if topic[0] == "$":
            # $SYS and whatever-else-dollar messages are not MoaT-KV's problem.
            await super().broadcast_message(session, topic, data, retain=retain)
            return

        if ts[: len(self.__base)] == self.__base:
            # All messages on "base" get stored in MoaT-KV, retained or not.
            try:
                await self.__client.set(ts, value=data)
            except Exception as exc:
                self.logger.error("Cannot set %s to %r: %r", ts, data, exc)

            return

        for t in self.__transparent:
            # Messages to be forwarded transparently. The "retain" flag is ignored.
            if len(ts) >= len(t) and t == ts[: len(t)]:
                await self.__client.msg_send(topic=ts, raw=data)
                return

        if self.__topic:
            # Anything else is encapsulated
            msg = dict(session=session.client_id, topic=topic, data=data, retain=retain)
            if qos is not None:
                msg["qos"] = qos
            if force_qos is not None:
                msg["force_qos"] = qos
            await self.__client.msg_send(topic=self.__topic, data=msg)
            return

        self.logger.info("Message ignored: %s %r", topic, data)
