"""
Victron Venus OS gateway.

Bridges a MoaT-Link subtree to a Venus OS device's MQTT API.

The destination is the Venus portal ID; subscriptions happen on
``N/<id>/...`` and writes go to ``W/<id>/...``.  A keep-alive request is
sent periodically to ``R/<id>/keepalive`` so the Venus device keeps
publishing updates.

Payloads on the Venus side are JSON.  The actual value lives in the
``value`` element of the payload dict; all other fields are added to the
imported message metadata.
"""

from __future__ import annotations

import anyio

from moat.util import NotGiven
from moat.lib.path import P, Path
from moat.link.meta import MsgMeta
from moat.link.node.codec import CodecNode

from .mqtt import Gate as _MqttGate

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from . import GateNode

    from typing import Any


params_info = """\
Venus gateway parameters (use ``-s KEY VALUE`` to set):

\b
  codec      Path to a codec-vector conversion tree (optional).
             Per element, ``codec`` selects the codec applied to the
             ``value`` field and ``speed`` gives the minimum delay in
             seconds between updates accepted from the device.
  keepalive  Keep-alive interval in seconds (default: 30).
  timeout    Seconds to wait for the initial data burst (default: 5).
  backend    Dict describing a separate MQTT broker;
             ``driver`` defaults to ``mqtt``.

The ``--dst`` argument is the Venus portal ID, e.g. ``--dst 48e7da87a52c``.\
"""


class Gate(_MqttGate):
    """Venus OS gateway driver.

    Subclasses the MQTT gateway, replacing the wire encoding with the
    JSON-with-``value``-wrapper convention used by Venus OS and adding a
    keep-alive publisher.
    """

    _read_prefix: Path
    _write_prefix: Path
    _keepalive_topic: Path
    _keepalive_interval: float

    async def setup_(self) -> None:
        """Compute Venus-specific topic prefixes and ensure ``cf.codec`` is set."""
        # mqtt.Gate.run_ reads ``self.cf.codec`` unconditionally; supply a
        # harmless default when the user didn't configure a codec-vector tree.
        if "codec" not in self.cf:
            self.cf.codec = "noop"
        await super().setup_()
        self._read_prefix = P("N") + self.cf.dst
        self._write_prefix = P("W") + self.cf.dst
        self._keepalive_topic = P("R") + self.cf.dst + P("keepalive")
        self._keepalive_interval = float(self.cf.get("keepalive", 30))

    def _lookup(self, path: Path) -> tuple[CodecNode | None, Any]:
        """Look up the codec node and vector entry for ``path``.

        Returns ``(codec_node, vd)`` or ``(None, None)`` when no
        codec-vector tree is configured or the lookup fails.
        """
        codecs = self.codecs
        codec_vecs = getattr(self, "codec_vecs", None)
        if codecs is None or codec_vecs is None:
            return None, None
        try:
            vd = codec_vecs.search(path)
            cd = codecs.get(Path.build(vd.data["codec"]))
        except (KeyError, ValueError):
            return None, None
        if not isinstance(cd, CodecNode):
            return None, None
        return cd, vd

    def _merge_meta(self, meta: MsgMeta | None, extras: dict[str, Any]) -> MsgMeta:
        """Return a metadata object carrying ``extras`` as additional kw entries."""
        if meta is None:
            new = MsgMeta(origin=self.origin)
        else:
            new = MsgMeta.restore(list(meta.a), dict(meta.kw))
        for k, v in extras.items():
            if k not in new.kw:
                new.kw[k] = v
        return new

    async def get_dst(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """Subscribe to ``N/<id>/...``, decode JSON payloads, drive keep-alive."""
        async with self.backend.monitor(self._read_prefix, subtree=True, codec="json") as mon:
            task_status.started()
            # Start keep-alive only once subscription is established so we
            # don't miss the initial data burst Venus emits in response.
            self.tg.start_soon(self._keepalive_loop)

            ld = len(self._read_prefix)
            timeout = float(self.cf.get("timeout", 5))

            async def _process(msg: Any) -> None:
                if msg.meta is not None and msg.meta.origin == self.origin:
                    return
                if not isinstance(msg.data, dict) or "value" not in msg.data:
                    return
                p = Path.build(msg.topic[ld:])
                value = msg.data["value"]
                extras = {k: v for k, v in msg.data.items() if k != "value"}
                cd, vd = self._lookup(p)
                if cd is not None:
                    try:
                        value = cd.dec_value(value)
                    except Exception as exc:
                        self.logger.error("Decode: %s %r: %r", p, value, exc)
                        return
                meta = self._merge_meta(msg.meta, extras)
                spd = None if vd is None else vd.data.get("speed", None)
                await self.set_src(p, value, meta, speed=spd)

            while True:
                try:
                    with anyio.fail_after(timeout):
                        msg = await anext(mon)
                except TimeoutError:
                    break
                await _process(msg)
            self.dst_is_current()

            async for msg in mon:
                await _process(msg)

    async def set_dst(self, path: Path, data: Any, meta: MsgMeta | None, node: GateNode) -> None:
        """Publish ``{"value": data}`` to ``W/<id>/...``."""
        if meta is None:
            out_meta = MsgMeta(origin=self.origin)
        else:
            out_meta = MsgMeta(origin=self.origin, timestamp=meta.timestamp)

        if data is NotGiven:
            # Venus has no delete operation; drop the update silently.
            node.ext_meta = out_meta
            return

        wire = data
        cd, _ = self._lookup(path)
        if cd is not None:
            try:
                wire = cd.enc_value(data)
            except Exception as exc:
                self.logger.error("Encode: %s %r: %r", path, data, exc)
                return
        elif self.codecs is not None:
            # A codec-vector tree is configured but the path isn't covered.
            self.logger.error("No codec: %s %r", path, data)
            return

        await self.backend.send(
            self._write_prefix + path,
            {"value": wire},
            codec="json",
            retain=False,
            meta=out_meta,
        )
        node.ext_meta = out_meta

    async def _keepalive_loop(self) -> None:
        """Periodically publish to ``R/<id>/keepalive`` to keep Venus talking."""
        while True:
            try:
                await self.backend.send(
                    self._keepalive_topic,
                    b"",
                    codec="noop",
                    retain=False,
                )
            except Exception as exc:
                self.logger.warning("Keep-alive failed: %r", exc)
            await anyio.sleep(self._keepalive_interval)
