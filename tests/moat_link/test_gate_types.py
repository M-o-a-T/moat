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
from moat.link.meta import MsgMeta


class _Remote:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, MsgMeta]] = []

    async def d_set(self, path, data, meta) -> None:
        self.calls.append((path, data, meta))


class _Link:
    def __init__(self) -> None:
        self.calls: list[tuple[object, object, bool, str, MsgMeta]] = []

    async def send(self, topic, data, *, retain, codec, meta) -> None:
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
