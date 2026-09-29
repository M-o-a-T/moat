"""Tests for the extended ``moat.lib.config.base.BaseModel``.

Covers the prerequisites of HEAT.md §2.4 / issue moat-n84.3:

* :class:`moat.lib.path.Path` fields accept a ``Path`` (YAML ``!P``) or a
  ``list``/``tuple``; under YAML context a bare dotted ``str`` is rejected
  (a forgotten ``!P``), while JSON / context-less validation still accepts
  strings.
* ``Path`` fields survive a round-trip through the standard CBOR codec and
  re-validation.
* (Nested) :class:`moat.util.attrdict` input validates.
* :meth:`BaseModel.from_cfg` reads a CFG subtree (YAML context).
* :meth:`BaseModel.cfg_monitor` yields a re-validated instance per change
  and skips invalid updates.
"""

from __future__ import annotations

import anyio
import json
import pytest

from pydantic import ValidationError

from moat.util import NotGiven, attrdict
from moat.lib.codec.moat_cbor import Codec
from moat.lib.config import CFG, CfgStore, current_cfg
from moat.lib.config.base import BaseModel
from moat.lib.path import P, Path

# Validation context used by ``from_cfg`` / ``cfg_monitor`` to mark data as
# originating from YAML (where bare dotted strings are forbidden).
_YAML_CTX = {"source": "yaml"}

# ── Models used across the tests ──────────────────────────────────────


class Leaf(BaseModel):
    """A model with a Path field and a scalar."""

    p: Path
    n: int = 0


class Nest(BaseModel):
    """A model embedding another model and a Path."""

    leaf: Leaf
    top: Path


# ── Path fields: accepted forms ────────────────────────────────────────


def test_path_accepts_path_list_and_json_str():
    """A Path field accepts a ``Path``, a ``list``/``tuple``, or (outside
    YAML context) a ``str`` parsed via ``P()``."""
    a = Leaf(p=P("a.b.c"))
    b = Leaf(p=["a", "b", "c"])
    c = Leaf(p=("a", "b", "c"))
    d = Leaf(p="a.b.c")  # JSON / no context: a string is fine
    for m in (a, b, c, d):
        assert isinstance(m.p, Path)
    assert a.p == b.p == c.p == d.p


def test_path_list_builds_path_elementwise():
    """A list input is built into a Path element-wise (compatibility form)."""
    m = Leaf(p=["heat", "s", "pump"])
    assert isinstance(m.p, Path)
    assert m.p == P("heat.s.pump")


# ── Path fields: YAML context forbids bare strings ────────────────────


def test_path_yaml_rejects_bare_string():
    """Under YAML context a bare dotted string is rejected (forgotten ``!P``)."""
    with pytest.raises(ValidationError):
        Leaf.model_validate({"p": "a.b.c"}, context=_YAML_CTX)
    with pytest.raises(ValidationError):
        Leaf.model_validate(attrdict(p="a.b.c"), context=_YAML_CTX)


def test_path_yaml_accepts_path_and_list():
    """Under YAML context a ``Path`` (``!P``) or a list are accepted."""
    a = Leaf.model_validate({"p": P("a.b.c")}, context=_YAML_CTX)
    b = Leaf.model_validate({"p": ["a", "b", "c"]}, context=_YAML_CTX)
    assert isinstance(a.p, Path)
    assert isinstance(b.p, Path)
    assert a.p == b.p == P("a.b.c")


def test_path_strict_rejects_bad_types():
    """Types that are not a ``Path``, list, or ``str`` are rejected."""
    for bad in (123, 1.5, None, True, False, {}, b"x"):
        with pytest.raises(ValidationError):
            Leaf(p=bad)  # type: ignore[arg-type]
    # Even under YAML, non-str/list/Path types are rejected.
    for bad in (123, 1.5, None, True, False, {}, b"x"):
        with pytest.raises(ValidationError):
            Leaf.model_validate({"p": bad}, context=_YAML_CTX)  # type: ignore[arg-type]


# ── Path fields: codec round-trips ────────────────────────────────────


def test_path_round_trip_cbor():
    """A Path field survives encode → decode → re-validation."""
    codec = Codec()
    m = Leaf(p=P("heat.s.pump.cmd.power"), n=3)

    dumped = m.model_dump(mode="python")
    # Python-mode serialisation keeps the Path object (needed for CBOR).
    assert isinstance(dumped["p"], Path)

    enc = codec.encode(dumped)
    dec = codec.decode(enc)
    assert dec == dumped  # codec reproduces the Path
    assert isinstance(dec["p"], Path)

    # Re-validation works under YAML context too (Path is kept, not a str).
    m2 = Leaf.model_validate(dec, context=_YAML_CTX)
    assert isinstance(m2.p, Path)
    assert m2 == m


def test_path_json_serialisation_is_string():
    """JSON serialisation emits the dotted-string form and re-validates."""
    m = Leaf(p="a.b.c", n=1)
    js = m.model_dump_json()
    assert json.loads(js)["p"] == "a.b.c"
    # JSON round-trip (no YAML context) accepts the string back.
    m2 = Leaf.model_validate(json.loads(js))
    assert m2 == m
    assert isinstance(m2.p, Path)


# ── attrdict input ───────────────────────────────────────────────────


def test_model_validate_attrdict():
    """``model_validate`` accepts a top-level attrdict."""
    m = Leaf.model_validate(attrdict(p="a.b", n=5))
    assert m.n == 5
    assert m.p == P("a.b")


def test_nested_attrdict_via_kwargs():
    """Constructor kwargs carrying a nested attrdict validate."""
    m = Nest(leaf=attrdict(p="x.y", n=2), top="m.n")
    assert m.leaf.n == 2
    assert m.top == P("m.n")


def test_deeply_nested_attrdict():
    """Deeply nested attrdicts validate at every level."""
    m = Nest.model_validate(attrdict(leaf=attrdict(p=":R.foo", n=9), top="a.b"))
    assert m.leaf.p == P(":R.foo")
    assert m.leaf.n == 9
    assert m.top == P("a.b")


def test_attrdict_with_extras():
    """Extra attrdict leaves are kept as pydantic extras."""
    m = Leaf.model_validate(attrdict(p="a.b", n=1, extra="kept"))
    assert m.__pydantic_extra__ == {"extra": "kept"}


def test_attrdict_yaml_context_rejects_bare_string():
    """A nested attrdict from YAML with a bare string Path is rejected."""
    with pytest.raises(ValidationError):
        Nest.model_validate(attrdict(leaf=attrdict(p="x.y", n=2), top="m.n"), context=_YAML_CTX)


# ── from_cfg ─────────────────────────────────────────────────────────


def _store_with(target: attrdict) -> CfgStore:
    """Build a CfgStore whose ``dev.heat.target`` subtree is *target*."""
    store = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    for k, v in target.items():
        store.mod(P(f"dev.heat.target.{k}"), v)
    store.redo()
    return store


def test_from_cfg_accepts_path():
    """``from_cfg`` validates a subtree whose Path comes in as ``!P``."""
    store = _store_with(attrdict(p=P("heat.s.pump.cmd.power"), n=7))
    with CFG.with_config_(store):
        m = Leaf.from_cfg(P("dev.heat.target"))
    assert m.p == P("heat.s.pump.cmd.power")
    assert m.n == 7


def test_from_cfg_accepts_list():
    """``from_cfg`` validates a subtree whose Path comes in as a list."""
    store = _store_with(attrdict(p=["heat", "s", "pump"], n=7))
    with CFG.with_config_(store):
        m = Leaf.from_cfg(P("dev.heat.target"))
    assert m.p == P("heat.s.pump")
    assert m.n == 7


def test_from_cfg_rejects_bare_string():
    """``from_cfg`` rejects a bare dotted string (YAML requires ``!P``)."""
    store = _store_with(attrdict(p="heat.s.pump.cmd.power", n=7))
    with CFG.with_config_(store), pytest.raises(ValidationError):
        Leaf.from_cfg(P("dev.heat.target"))


def test_from_cfg_accepts_str_path_argument():
    """``from_cfg`` accepts a dotted-string *path argument* (not a value)."""
    store = _store_with(attrdict(p=P("a.b"), n=4))
    with CFG.with_config_(store):
        m = Leaf.from_cfg("dev.heat.target")
    assert m.n == 4
    assert m.p == P("a.b")


def test_from_cfg_missing_subtree_uses_defaults():
    """A missing subtree validates against the model defaults."""
    store = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    store.redo()
    with CFG.with_config_(store):
        # ``Leaf.p`` has no default, so a missing subtree must fail — but a
        # model whose required fields all have defaults would succeed.
        with pytest.raises(ValidationError):
            Leaf.from_cfg(P("dev.heat.absent"))

        class WithDefaults(BaseModel):
            n: int = 42

        assert WithDefaults.from_cfg(P("dev.heat.absent")).n == 42


def test_from_cfg_no_active_config_raises():
    """Without an active config ``from_cfg`` raises ``RuntimeError``."""
    # Ensure no config is active in this context.
    assert current_cfg.get() is None
    with pytest.raises(RuntimeError):
        Leaf.from_cfg(P("dev.heat.target"))


# ── cfg_monitor ──────────────────────────────────────────────────────


@pytest.mark.anyio
async def test_cfg_monitor_yields_valid_changes():
    """``cfg_monitor`` yields a fresh validated instance per change.

    Like :class:`moat.lib.config.monitor`, ``cfg_monitor`` yields on
    *changes* only (there is no initial snapshot), one validated instance
    per detected change.
    """
    store = _store_with(attrdict(p=P("a.b"), n=1))
    received: list[Leaf] = []

    async def watcher() -> None:
        with CFG.with_config_(store):
            async for inst in Leaf.cfg_monitor(P("dev.heat.target"), delay=0.05):
                received.append(inst)
                if len(received) >= 2:
                    break

    async with anyio.create_task_group() as tg:
        tg.start_soon(watcher)
        await anyio.sleep(0.1)
        # first change → first yield
        store.mod(P("dev.heat.target.n"), 50)
        store.redo()
        await anyio.sleep(0.1)
        # second change → second yield
        store.mod(P("dev.heat.target.n"), 99)
        store.redo()
        await anyio.sleep(0.1)
        tg.cancel_scope.cancel()

    assert [r.n for r in received] == [50, 99]
    assert all(isinstance(r.p, Path) for r in received)


@pytest.mark.anyio
async def test_cfg_monitor_skips_invalid(caplog):
    """An invalid update is skipped; the previous instance stays in effect."""
    store = _store_with(attrdict(p=P("a.b"), n=1))
    received: list[Leaf] = []

    async def watcher() -> None:
        with CFG.with_config_(store):
            async for inst in Leaf.cfg_monitor(P("dev.heat.target"), delay=0.05):
                received.append(inst)
                if len(received) >= 2:
                    break

    async with anyio.create_task_group() as tg:
        tg.start_soon(watcher)
        await anyio.sleep(0.1)
        # valid change → yielded
        store.mod(P("dev.heat.target.n"), 5)
        store.redo()
        await anyio.sleep(0.1)
        # invalid change (wrong type for ``n``) → skipped, logged
        store.mod(P("dev.heat.target.n"), "not-an-int")
        store.redo()
        await anyio.sleep(0.1)
        # valid again → yielded
        store.mod(P("dev.heat.target.n"), 8)
        store.redo()
        await anyio.sleep(0.1)
        tg.cancel_scope.cancel()

    assert len(received) == 2
    assert [r.n for r in received] == [5, 8]
    # The invalid update was logged at WARNING level.
    rec = [r for r in caplog.records if "Invalid config" in r.message]
    assert rec, "invalid update should be logged"


@pytest.mark.anyio
async def test_cfg_monitor_skips_bare_string_path(caplog):
    """A change introducing a bare-string Path is skipped (YAML requires ``!P``)."""
    store = _store_with(attrdict(p=P("a.b"), n=1))
    received: list[Leaf] = []

    async def watcher() -> None:
        with CFG.with_config_(store):
            async for inst in Leaf.cfg_monitor(P("dev.heat.target"), delay=0.05):
                received.append(inst)
                if len(received) >= 1:
                    break

    async with anyio.create_task_group() as tg:
        tg.start_soon(watcher)
        await anyio.sleep(0.1)
        # Replace the Path value with a bare string → invalid under YAML.
        store.mod(P("dev.heat.target.p"), "bare.string")
        store.redo()
        await anyio.sleep(0.1)
        # Restore a valid Path → yielded.
        store.mod(P("dev.heat.target.p"), P("c.d"))
        store.redo()
        await anyio.sleep(0.1)
        tg.cancel_scope.cancel()

    assert len(received) == 1
    assert received[0].p == P("c.d")
    rec = [r for r in caplog.records if "Invalid config" in r.message]
    assert rec, "bare-string update should be logged and skipped"


@pytest.mark.anyio
async def test_cfg_monitor_no_active_config_raises():
    """Iterating ``cfg_monitor`` with no active config raises ``RuntimeError``."""
    assert current_cfg.get() is None
    with pytest.raises(RuntimeError):
        async for _inst in Leaf.cfg_monitor(P("dev.heat.target")):  # pragma: no cover
            pass
