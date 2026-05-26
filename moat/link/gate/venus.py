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

from moat.util import NotGiven, gen_ident
from moat.lib.path import P, Path
from moat.link.meta import MsgMeta
from moat.link.node.codec import CodecNode

from . import Gate as _BaseGate
from .mqtt import Gate as _MqttGate
from .mqtt import _is_null

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
  speed      Default minimum delay between updates, applied when the
             codec entry doesn't carry its own ``speed`` (default: 1.0).
  keepalive  Keep-alive interval in seconds (default: 30).
  timeout    Seconds to wait for the initial full-publish-completed
             echo (default: 30).
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

    #: Fallback for ``set_src`` rate limiting when neither the codec entry
    #: nor ``cf.speed`` provide a value.  Venus often emits very frequent
    #: updates, so we default to one second.
    DEFAULT_SPEED: float = 1.0

    #: Topic suffix Venus uses to signal completion of the initial publish.
    COMPLETION_TOPIC: str = "full_publish_completed"

    _read_prefix: Path
    _write_prefix: Path
    _keepalive_topic: Path
    _keepalive_interval: float
    _keepalive_id: str

    async def setup_(self) -> None:
        """Compute Venus-specific topic prefixes and per-run keep-alive ID."""
        await super().setup_()
        self._read_prefix = P("N") + self.cf.dst
        self._write_prefix = P("W") + self.cf.dst
        self._keepalive_topic = P("R") + self.cf.dst + P("keepalive")
        self._keepalive_interval = float(self.cf.get("keepalive", 30))
        # Random per-run identifier echoed by Venus in the initial
        # ``full_publish_completed`` message so we can ignore stale
        # completions from earlier runs.
        self._keepalive_id = gen_ident(8)
        # Apply the Venus-specific default rate limit when the user hasn't
        # set one explicitly via ``cf.speed``.
        if "speed" not in self.cf:
            self._speed = self.DEFAULT_SPEED

    async def run_(self, *, task_status=anyio.TASK_STATUS_IGNORED) -> None:
        """Optionally fetch the codec-vector tree, then run the base gate.

        Overrides :py:meth:`moat.link.gate.mqtt.Gate.run_` so that a
        Venus gate may run without a ``codec`` entry: Venus payloads are
        always JSON-wrapped and don't need a wire codec.  Mutating
        ``self.cf`` here would break the equality check in
        :py:meth:`moat.link.gate.Gate._restart`.
        """
        cfg_codec = self.cf.get("codec", None)
        if isinstance(cfg_codec, Path):
            async with self.link.d_watch(
                P("conv") + cfg_codec, subtree=True, state=None, meta=False
            ) as cdv:
                self.codec_vecs = await cdv.get_node()
            self.codecs = await self.link.get_codec_tree()
        # Skip mqtt.Gate.run_ (we just replicated its codec setup);
        # delegate directly to the base implementation.
        await _BaseGate.run_(self, task_status=task_status)

    def _lookup(self, path: Path) -> tuple[CodecNode | None, Any]:
        """Look up the codec node and vector entry for ``path``.

        Returns ``(codec_node, vd)`` or ``(None, None)`` when no
        codec-vector tree is configured or the lookup fails.

        If the codec-vector entry selects the null codec
        (``data['codec'] == 'null'``), ``cd`` is ``None`` and ``vd`` is
        returned so callers can detect the placeholder and drop the item.
        """
        codecs = self.codecs
        codec_vecs = getattr(self, "codec_vecs", None)
        if codecs is None or codec_vecs is None:
            return None, None
        try:
            vd = codec_vecs.search(path)
        except (KeyError, ValueError):
            return None, None
        if _is_null(vd):
            return None, vd
        try:
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
            timeout = float(self.cf.get("timeout", 30))

            def _is_completion(p: Path) -> bool:
                return len(p) == 1 and p[0] == self.COMPLETION_TOPIC

            async def _process(p: Path, msg: Any) -> None:
                if msg.meta is not None and msg.meta.origin == self.origin:
                    return
                if not isinstance(msg.data, dict) or "value" not in msg.data:
                    return
                value = msg.data["value"]
                extras = {k: v for k, v in msg.data.items() if k != "value"}
                cd, vd = self._lookup(p)
                if _is_null(vd):
                    return
                if cd is not None:
                    try:
                        value = cd.dec_value(value)
                    except Exception as exc:
                        self.logger.error("Decode: %s %r: %r", p, value, exc)
                        return
                meta = self._merge_meta(msg.meta, extras)
                spd = None if vd is None else vd.data.get("speed", None)
                await self.set_src(p, value, meta, speed=spd)

            # Wait for Venus to signal completion of the initial publish
            # via ``N/<id>/full_publish_completed`` carrying our keep-alive
            # ID.  If that doesn't arrive within ``timeout`` seconds, raise
            # an error so the operator knows the device isn't responding.
            try:
                with anyio.fail_after(timeout):
                    async for msg in mon:
                        p = Path.build(msg.topic[ld:])
                        if _is_completion(p):
                            if (
                                isinstance(msg.data, dict)
                                and msg.data.get("full-publish-completed-echo")
                                == self._keepalive_id
                            ):
                                break
                            # Stale echo from a previous run; keep waiting.
                            continue
                        await _process(p, msg)
                    else:
                        raise RuntimeError(
                            f"Venus monitor stream for {self.cf.dst} ended "
                            "before full-publish-completed",
                        )
            except TimeoutError as exc:
                raise RuntimeError(
                    f"Venus device {self.cf.dst} did not signal "
                    f"full-publish-completed within {timeout}s",
                ) from exc
            self.dst_is_current()

            async for msg in mon:
                p = Path.build(msg.topic[ld:])
                # ``suppress-republish`` should prevent further completion
                # echoes, but filter them out defensively just in case.
                if _is_completion(p):
                    continue
                await _process(p, msg)

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
        cd, vd = self._lookup(path)
        if _is_null(vd):
            # Null-codec placeholder: silently drop outbound writes.
            node.ext_meta = out_meta
            return
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
        """Periodically publish to ``R/<id>/keepalive`` to keep Venus talking.

        The first keep-alive carries the ``full-publish-completed-echo``
        option, asking Venus to signal completion of the initial publish.
        Subsequent keep-alives carry ``suppress-republish`` so the device
        merely maintains the session instead of dumping its whole state
        on every tick.

        Send failures are intentionally not caught: a broken keep-alive
        link should propagate and tear the gate down.
        """
        await self.backend.send(
            self._keepalive_topic,
            {
                "keepalive-options": [
                    {"full-publish-completed-echo": self._keepalive_id},
                ],
            },
            codec="json",
            retain=False,
        )
        while True:
            await anyio.sleep(self._keepalive_interval)
            await self.backend.send(
                self._keepalive_topic,
                {"keepalive-options": ["suppress-republish"]},
                codec="json",
                retain=False,
            )
