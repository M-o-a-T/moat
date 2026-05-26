"""Coverage tests for gate metadata handling."""

from __future__ import annotations

import anyio
import pytest
from types import SimpleNamespace

from moat.util import NotGiven
from moat.lib.path import P
from moat.lib.priomap import TimerMap
from moat.link.gate import DelayedGate, GateNode, _DelayedUpdate
from moat.link.gate.link import Gate as LinkGate
from moat.link.gate.mqtt import Gate as MqttGate
from moat.link.gate.venus import Gate as VenusGate
from moat.link.meta import MsgMeta


class _Remote:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, MsgMeta]] = []

    async def d_set(self, path, data, meta) -> None:
        self.calls.append((path, data, meta))


class _Link:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, bool, str, MsgMeta | None]] = []

    async def send(self, topic, data, *, retain=False, codec=None, meta=None, **kw) -> None:
        kw  # noqa:B018
        self.calls.append((topic, data, retain, codec, meta))


@pytest.mark.anyio
async def test_delayed_gate_pending_to_dst_uses_meta_fallback() -> None:
    """DelayedGate should synthesize metadata if none is available."""
    gate = object.__new__(DelayedGate)
    gate.origin = "via:test"
    gate._pending = TimerMap()  # noqa: SLF001
    gate.cf = SimpleNamespace(src=P("s"))

    node = GateNode()
    seen: list[MsgMeta] = []

    async def _set_dst(path, data, meta, node_) -> None:
        assert path == P("x")
        assert data == 1
        assert node_ is node
        seen.append(meta)

    gate.set_dst = _set_dst
    gate._pending[_DelayedUpdate(path=P("x"), data=1, meta=None, node=node, to_dst=True)] = -1  # noqa: SLF001

    with anyio.move_on_after(0.05):
        await gate._process_pending(gate._pending)  # noqa: SLF001

    assert len(seen) == 1
    assert isinstance(seen[0], MsgMeta)
    assert node.todo is False


@pytest.mark.anyio
async def test_delayed_gate_pending_to_src_clears_source() -> None:
    """DelayedGate should clear source state after writing source update."""
    gate = object.__new__(DelayedGate)
    gate.origin = "via:test"
    gate._pending = TimerMap()  # noqa: SLF001
    gate._speed_pending = {}  # noqa: SLF001
    gate.cf = SimpleNamespace(src=P("s"))
    gate.link = _Remote()

    def _is_update(_node, _data, _meta) -> bool:
        return True

    gate.is_update = _is_update

    node = GateNode()
    node.set_(P("n"), 9, MsgMeta(origin="old"))
    meta = MsgMeta(origin="remote")
    gate._pending[_DelayedUpdate(path=P("x"), data=3, meta=meta, node=node, to_dst=False)] = -1  # noqa: SLF001

    with anyio.move_on_after(0.05):
        await gate._process_pending(gate._pending)  # noqa: SLF001

    assert gate.link.calls[0][0] == P("s.x")
    assert node.data_ is NotGiven
    assert node.ext_data == 3
    assert node.ext_meta == meta


@pytest.mark.anyio
async def test_link_gate_metadata_paths() -> None:
    """Link gate metadata helpers handle optional metadata."""
    gate = object.__new__(LinkGate)
    gate.origin = "via:test"
    gate.cf = SimpleNamespace(src=P("r"))
    gate._skip_paths = frozenset(["run"])  # noqa: SLF001
    gate._remote = _Remote()  # noqa: SLF001

    node = GateNode()
    await gate.set_dst(P("a"), 2, None, node)
    assert gate._remote.calls[0][0] == P("r.a")  # noqa: SLF001

    m1 = MsgMeta(origin="x", timestamp=1)
    node.ext_meta = m1
    assert gate.is_update(node, 2, MsgMeta(origin="x", timestamp=1)) is False
    assert gate.is_update(node, 2, None) is True

    node.set_(P("a"), 2, MsgMeta(origin="local", timestamp=2))
    node.ext_meta = MsgMeta(origin="remote", timestamp=4)
    assert gate.newer_dst(node) is True


@pytest.mark.anyio
async def test_mqtt_gate_metadata_paths() -> None:
    """MQTT gate handles optional metadata in set/update checks."""
    gate = object.__new__(MqttGate)
    gate.origin = "via:test"
    gate.cf = SimpleNamespace(dst=P("d"))
    gate.link = _Link()
    gate.backend = gate.link  # mirrors what run_() sets when no separate backend is given
    gate.codecs = None
    gate.codec = "cbor"

    node = GateNode()
    await gate.set_dst(P("a"), 2, None, node)
    await gate.set_dst(P("a"), NotGiven, MsgMeta(origin="x", timestamp=1), node)
    assert len(gate.link.calls) == 2
    assert isinstance(gate.link.calls[0][4], MsgMeta)

    node.ext_meta = MsgMeta(origin="x", timestamp=1)
    assert gate.is_update(node, 0, None) is True
    assert gate.is_update(node, 0, MsgMeta(origin="x", timestamp=1)) is False


def _make_venus_gate() -> VenusGate:
    gate = object.__new__(VenusGate)
    gate.origin = "via:venus"
    gate.cf = SimpleNamespace(dst=P("abc"), get=lambda _k, d=None: d)
    gate.link = _Link()
    gate.backend = gate.link
    gate.codecs = None
    gate.codec = "json"
    gate._read_prefix = P("N") + gate.cf.dst  # noqa: SLF001
    gate._write_prefix = P("W") + gate.cf.dst  # noqa: SLF001
    gate._keepalive_topic = P("R") + gate.cf.dst + P("keepalive")  # noqa: SLF001
    gate._keepalive_interval = 0.01  # noqa: SLF001
    return gate


@pytest.mark.anyio
async def test_venus_gate_set_dst_wraps_json() -> None:
    """Venus set_dst wraps payloads as {'value': ...} on the W/ prefix."""
    gate = _make_venus_gate()
    node = GateNode()
    await gate.set_dst(P("system.0.Voltage"), 12.7, None, node)
    assert len(gate.link.calls) == 1
    topic, data, retain, codec, meta = gate.link.calls[0]
    assert topic == P("W.abc.system.0.Voltage")
    assert data == {"value": 12.7}
    assert retain is False
    assert codec == "json"
    assert isinstance(meta, MsgMeta)
    assert node.ext_meta is meta


@pytest.mark.anyio
async def test_venus_gate_set_dst_notgiven_is_noop() -> None:
    """Venus has no delete operation; NotGiven must not publish anything."""
    gate = _make_venus_gate()
    node = GateNode()
    await gate.set_dst(P("x"), NotGiven, MsgMeta(origin="src", timestamp=2), node)
    assert gate.link.calls == []
    assert isinstance(node.ext_meta, MsgMeta)


def test_venus_gate_merge_meta_adds_extras() -> None:
    """Extras from the JSON payload are added to the metadata kw dict."""
    gate = _make_venus_gate()
    base = MsgMeta(origin="venus-mqtt", timestamp=10)
    merged = gate._merge_meta(base, {"min": 0, "max": 100, "text": "V"})  # noqa: SLF001
    assert merged.kw["min"] == 0
    assert merged.kw["max"] == 100
    assert merged.kw["text"] == "V"
    assert merged.origin == "venus-mqtt"
    # Existing kw entries are not overwritten.
    base2 = MsgMeta(origin="x", timestamp=1, text="keep")
    merged2 = gate._merge_meta(base2, {"text": "drop"})  # noqa: SLF001
    assert merged2.kw["text"] == "keep"
    # ``None`` metadata yields a fresh MsgMeta with our origin.
    merged3 = gate._merge_meta(None, {"unit": "V"})  # noqa: SLF001
    assert merged3.origin == gate.origin
    assert merged3.kw["unit"] == "V"


def test_venus_gate_lookup_no_codec_tree() -> None:
    """Without a codec-vector tree, ``_lookup`` returns ``(None, None)``."""
    gate = _make_venus_gate()
    assert gate._lookup(P("any.path")) == (None, None)  # noqa: SLF001


@pytest.mark.anyio
async def test_venus_gate_keepalive_publishes() -> None:
    """The keep-alive loop publishes JSON requests to R/<id>/keepalive."""
    gate = _make_venus_gate()
    with anyio.move_on_after(0.05):
        await gate._keepalive_loop()  # noqa: SLF001
    assert len(gate.link.calls) >= 2
    # All keep-alives go to the same topic, encoded as JSON.
    topics = {call[0] for call in gate.link.calls}
    assert topics == {P("R.abc.keepalive")}
    assert all(call[3] == "json" for call in gate.link.calls)
    # The first keep-alive asks Venus for a completion echo.
    assert gate.link.calls[0][1] == {
        "keepalive-options": ["full-publish-completed-echo"],
    }
    # Subsequent keep-alives suppress the full republish.
    assert gate.link.calls[1][1] == {"keepalive-options": ["suppress-republish"]}


@pytest.mark.anyio
async def test_venus_gate_keepalive_propagates_send_errors() -> None:
    """A failing keep-alive must propagate instead of being swallowed."""

    class _BoomLink:
        async def send(self, *a, **kw) -> None:
            a  # noqa:B018
            kw  # noqa:B018
            raise RuntimeError("network down")

    gate = _make_venus_gate()
    gate.backend = _BoomLink()
    with pytest.raises(RuntimeError, match="network down"):
        await gate._keepalive_loop()  # noqa: SLF001
