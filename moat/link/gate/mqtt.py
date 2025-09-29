"""
MoaT gateway
"""

from __future__ import annotations

import anyio
from contextlib import AsyncExitStack

from moat.util import NotGiven, P, Path
from moat.link.meta import MsgMeta

from . import Gate as _Gate

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.node.codec import CodecNode

    from . import GateNode

    from typing import Any


class Gate(_Gate):  # noqa: D101
    codecs: CodecNode | None = None

    async def run_(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        "Main loop. Overridden to fetch the codecs"
        async with AsyncExitStack() as ex:
            if isinstance(self.cf.codec, Path):
                cdv = await ex.enter_async_context(
                    self.link.d_watch(
                        P("conv") + self.cf.codec, subtree=True, state=None, meta=False
                    )
                )
                self.codec_vecs = await cdv.get_node()

                self.codecs = await self.link.get_codec_tree()

            await super().run_(task_status=task_status)

    async def get_dst(self, *, task_status=anyio.TASK_STATUS_IGNORED):  # noqa: D102
        async with AsyncExitStack() as ex:
            if self.codecs is not None:
                codec = "noop"

                def conv(p, d):
                    # two step
                    # (a) look up the codec type in the vector
                    try:
                        vd = self.codec_vecs.search(p)
                        cd = self.codecs.get(Path.build(vd.data["codec"]))
                    except (KeyError, ValueError):
                        return NotGiven
                    try:
                        return cd.dec_value(d)
                    except Exception as exc:
                        self.logger.error("Decode: %s %r: %r", p, d, exc)
                        return NotGiven

            else:
                codec = self.codec

                def conv(p, d):
                    p  # noqa:B018
                    return d

            mon = await ex.enter_async_context(
                self.link.monitor(self.cf.dst, subtree=True, codec=codec)
            )
            task_status.started()
            ld = len(self.cf.dst)
            while True:
                try:
                    with anyio.fail_after(self.cf.get("timeout", 0.5)):
                        msg = await anext(mon)
                except TimeoutError:
                    break
                p = Path.build(msg.topic[ld:])
                res = conv(p, msg.data)
                if res is NotGiven:
                    continue
                await self.set_src(p, res, msg.meta)
            self.dst_is_current()

            async for msg in mon:
                if msg.meta is not None and msg.meta.origin == self.origin:
                    # mine, so skip
                    continue
                p = Path.build(msg.topic[ld:])
                if msg.data == b"":
                    res = NotGiven
                else:
                    res = conv(p, msg.data)
                    if res is NotGiven:
                        continue
                await self.set_src(p, res, msg.meta)

    async def set_dst(self, path: Path, data: Any, meta: MsgMeta, node: GateNode):  # noqa: D102
        meta = MsgMeta(origin=self.origin, timestamp=meta.timestamp)
        if data is NotGiven:
            await self.link.send(self.cf.dst + path, b"", retain=True, codec="noop", meta=meta)
        elif self.codecs is not None:
            try:
                vd = self.codec_vecs.search(path)
                cd = self.codecs.get(Path.build(vd.data["codec"]))
            except (ValueError, KeyError):
                self.logger.error("No codec: %s %r", path, data)
                return
            res = cd.enc_value(data)
            if isinstance(res, (str, bytes, bytearray)):
                await self.link.send(self.cf.dst + path, res, retain=True, codec="noop", meta=meta)
            else:
                self.logger.error("Bad codec: %s %r > %r", path, data, res)

        else:
            await self.link.send(
                self.cf.dst + path, data, retain=True, codec=self.codec, meta=meta
            )

        node.ext_meta = meta

    def is_update(self, node: GateNode, data: Any, meta: MsgMeta):
        """
        Test whether this is an update.

        @data is currently ignored.
        """
        data  # noqa:B018
        # if the old metadata match the new, it's not an update.
        try:
            if node.ext_meta.origin == meta.origin and node.ext_meta.timestamp == meta.timestamp:
                return False
        except (AttributeError, KeyError):
            pass
        return True

    def newer_dst(self, node):  # noqa: D102
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
