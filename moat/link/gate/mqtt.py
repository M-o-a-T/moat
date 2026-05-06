"""
MoaT gateway
"""

from __future__ import annotations

import anyio

from moat.util import NotGiven, gen_ident
from moat.lib.path import P, Path
from moat.link.backend import Backend, get_backend
from moat.link.meta import MsgMeta
from moat.link.node.codec import CodecNode

from . import Gate as _Gate

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.client import Link

    from . import GateNode

    from typing import Any


class Gate(_Gate):
    """MQTT gateway driver.

    Bridges a MoaT-Link subtree (``cf.src``) to a raw MQTT topic tree
    (``cf.dst``).  By default the gateway reuses the primary MoaT-Link
    MQTT connection.  When ``cf.backend`` is present, a dedicated
    connection to a separate broker is opened instead and kept alive for
    the lifetime of the gateway.

    Configuration keys (stored at ``:R.gate.NAME``):

    Attributes:
        cf.src: Source path inside MoaT-Link.
        cf.dst: Destination topic prefix on the external MQTT broker.
        cf.codec: Codec name or path to conversion-vector tree.
        cf.backend: Optional dict describing a separate MQTT broker.
            Supports all keys accepted by :class:`moat.link.backend.mqtt.Backend`;
            ``driver`` defaults to ``mqtt``.
    """

    codecs: CodecNode | None = None

    backend: Backend | Link

    async def setup_(self) -> None:
        """Enter the gate-specific backend into ``self.ex`` before ``self.tg`` is created."""
        try:
            bcfg = self.cf.backend
        except AttributeError:
            self.backend = self.link
        else:
            if "driver" not in bcfg:
                bcfg.driver = "mqtt"
            name = "gate_" + gen_ident()
            self.backend = await self.ex.enter_async_context(
                get_backend({"backend": bcfg}, name=name)
            )

    async def run_(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "Main loop. Overridden to fetch the codecs"
        if isinstance(self.cf.codec, Path):
            # The watcher must live within self.tg's scope (Trio's strict
            # LIFO nursery rule): use a local context here.
            # TODO: The codec-vector node therefore doesn't receive live
            # updates after run_() returns; fix this properly once the
            # Watcher API grows a task-group-free update path.
            async with self.link.d_watch(
                P("conv") + self.cf.codec, subtree=True, state=None, meta=False
            ) as cdv:
                self.codec_vecs = await cdv.get_node()
            self.codecs = await self.link.get_codec_tree()

        await super().run_(task_status=task_status)

    async def get_dst(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "fetch destination"
        if self.codecs is not None:
            codecs = self.codecs
            codec = "noop"

            def conv(p, d):
                # two step
                # (a) look up the codec type in the vector
                try:
                    vd = self.codec_vecs.search(p)
                    cd = codecs.get(Path.build(vd.data["codec"]))
                    if not isinstance(cd, CodecNode):
                        return NotGiven, None
                except (KeyError, ValueError):
                    return NotGiven, None
                # (b) decode it
                try:
                    return cd.dec_value(d), vd
                except Exception as exc:
                    self.logger.error("Decode: %s %r: %r", p, d, exc)
                    return NotGiven, None

        else:
            codec = self.codec

            def conv(p, d):
                p  # noqa:B018
                return d, None

        async with self.backend.monitor(self.cf.dst, subtree=True, codec=codec) as mon:
            task_status.started()
            ld = len(self.cf.dst)
            while True:
                try:
                    with anyio.fail_after(self.cf.get("timeout", 0.5)):
                        msg = await anext(mon)
                except TimeoutError:
                    break
                p = Path.build(msg.topic[ld:])
                res, vd = conv(p, msg.data)
                if res is NotGiven:
                    continue

                spd = None if vd is None else vd.get("speed", None)
                await self.set_src(p, res, msg.meta, speed=spd)
            self.dst_is_current()

            async for msg in mon:
                if msg.meta is not None and msg.meta.origin == self.origin:
                    # mine, so skip
                    continue
                p = Path.build(msg.topic[ld:])
                if msg.data == b"":
                    res = NotGiven
                    spd = None
                else:
                    res, vd = conv(p, msg.data)
                    if res is NotGiven:
                        continue
                    spd = None if vd is None else vd.get("speed", None)
                await self.set_src(p, res, msg.meta)

    async def set_dst(self, path: Path, data: Any, meta: MsgMeta | None, node: GateNode):
        "update destination"
        if meta is None:
            meta = MsgMeta(origin=self.origin)
        else:
            meta = MsgMeta(origin=self.origin, timestamp=meta.timestamp)
        if data is NotGiven:
            await self.backend.send(self.cf.dst + path, b"", retain=True, codec="noop", meta=meta)
        elif self.codecs is not None:
            codecs = self.codecs
            try:
                vd = self.codec_vecs.search(path)
                cd = codecs.get(Path.build(vd.data["codec"]))
                if not isinstance(cd, CodecNode):
                    self.logger.error("Bad codec node: %s", path)
                    return
            except (ValueError, KeyError):
                self.logger.error("No codec: %s %r", path, data)
                return
            try:
                res = cd.enc_value(data)
            except Exception as exc:
                self.logger.error("Encode: %s %r: %r", path, data, exc)
            else:
                if isinstance(res, (str, bytes, bytearray)):
                    await self.backend.send(
                        self.cf.dst + path, res, retain=True, codec="noop", meta=meta
                    )
                else:
                    self.logger.error("Bad codec: %s %r > %r", path, data, res)

        else:
            await self.backend.send(
                self.cf.dst + path, data, retain=True, codec=self.codec, meta=meta
            )

        node.ext_meta = meta

    def is_update(self, node: GateNode, data: Any, aux: MsgMeta | None) -> bool:
        """
        Test whether this is an update.

        @data is currently ignored.
        """
        data  # noqa:B018
        if aux is None:
            return True
        # if the old metadata match the new, it's not an update.
        try:
            if node.ext_meta.origin == aux.origin and node.ext_meta.timestamp == aux.timestamp:
                return False
        except (AttributeError, KeyError):
            pass
        return True

    def newer_dst(self, node):
        "Check for newer metadata"
        # If the external message has no metadata, it can't be from us,
        # thus assume it's newer.
        if not node.ext_meta:
            return True

        # If the internal and external metadata match, the message is from
        # us, so nothing to do.
        if self.origin == node.ext_meta.origin:
            return None

        # If the internal message has a copy of the outside metadata, it's
        # either unmodified or older. Test the data to be sure.
        if "gw" in node.meta:
            if node.meta["gw"] == node.ext_meta:
                return None if node.data_ == node.ext_data else True
            else:
                return True

        # Otherwise, if the external message is ours, it's old.
        if node.ext_meta.origin == self.origin:
            return False

        # if the timestamps are too close, there might be a problem.
        if abs(node.ext_meta.timestamp - node.meta.timestamp) < 0.1:
            return None

        # Otherwise use the message with the newer timestamp.
        return node.ext_meta.timestamp > node.meta.timestamp
