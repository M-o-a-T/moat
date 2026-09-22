"""Tests for NotGiven handling during config reload and safe_reload."""

from __future__ import annotations

import copy
from contextlib import suppress

from moat.util import NotGiven, attrdict
from moat.lib.config import CfgStore
from moat.lib.config._impl import _has_notgiven
from moat.lib.path import P

# ── NotGiven deletion via mod + redo ────────────────────────────────


def test_notgiven_deletes_existing_key():
    """``mod(path, NotGiven)`` followed by ``redo`` removes the key."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.foo"), "bar")
    cfg.mod(P("data.baz"), "qux")
    cfg.redo()

    assert cfg.result.data.foo == "bar"
    assert cfg.result.data.baz == "qux"

    cfg.mod(P("data.foo"), NotGiven)
    cfg.redo()

    assert "foo" not in cfg.result.data
    assert cfg.result.data.baz == "qux"


def test_notgiven_deletes_nested_key():
    """Deleting a deeply nested key works."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("a.b.c.d"), 1)
    cfg.mod(P("a.b.c.e"), 2)
    cfg.redo()

    assert cfg.result.a.b.c.d == 1
    assert cfg.result.a.b.c.e == 2

    cfg.mod(P("a.b.c.d"), NotGiven)
    cfg.redo()

    assert "d" not in cfg.result.a.b.c
    assert cfg.result.a.b.c.e == 2


def test_notgiven_deletes_nonexistent_key():
    """Deleting a key that doesn't exist yet is a no-op (converges)."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.present"), "yes")
    cfg.redo()

    # Delete a key that was never set
    cfg.mod(P("data.absent"), NotGiven)
    cfg.redo()

    assert "absent" not in cfg.result.data
    assert cfg.result.data.present == "yes"
    # No NotGiven leaked into the result
    assert not _has_notgiven(cfg.result)


def test_notgiven_add_then_delete_same_cycle():
    """Adding and then deleting a key in the same redo cycle converges."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.temp"), "value")
    cfg.redo()

    # Overwrite with a new value, then delete it
    cfg.mod(P("data.temp"), "updated")
    cfg.mod(P("data.temp"), NotGiven)
    cfg.redo()

    assert "temp" not in cfg.result.data
    assert not _has_notgiven(cfg.result)


def test_notgiven_multiple_deletions_converge():
    """Multiple simultaneous NotGiven deletions converge in one redo."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    for i in range(5):
        cfg.mod(P(f"data.key{i}"), f"value{i}")
    cfg.redo()

    assert len(cfg.result.data) == 5

    # Delete all at once
    for i in range(5):
        cfg.mod(P(f"data.key{i}"), NotGiven)
    cfg.redo()

    assert len(cfg.result.data) == 0
    assert not _has_notgiven(cfg.result)


def test_notgiven_partial_deletion_keeps_others():
    """Deleting some keys preserves siblings."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("svc.a"), 1)
    cfg.mod(P("svc.b"), 2)
    cfg.mod(P("svc.c"), 3)
    cfg.redo()

    cfg.mod(P("svc.b"), NotGiven)
    cfg.redo()

    assert cfg.result.svc.a == 1
    assert "b" not in cfg.result.svc
    assert cfg.result.svc.c == 3


# ── NotGiven + safe_reload ──────────────────────────────────────────


def test_safe_reload_with_notgiven_deletion():
    """safe_reload correctly applies NotGiven deletions."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.foo"), "bar")
    cfg.mod(P("data.keep"), "yes")
    cfg.redo()

    cfg.mod(P("data.foo"), NotGiven)
    ok = cfg.safe_reload()

    assert ok is True
    assert "foo" not in cfg.result.data
    assert cfg.result.data.keep == "yes"
    assert not _has_notgiven(cfg.result)


def test_safe_reload_failure_preserves_config_with_pending_notgiven():
    """A failed safe_reload preserves old config even when NotGiven
    deletions are pending."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.foo"), "bar")
    cfg.mod(P("data.baz"), "qux")
    cfg.redo()

    # Schedule a deletion
    cfg.mod(P("data.foo"), NotGiven)

    # Sabotage redo
    orig_redo = cfg.redo

    def failing_redo() -> None:
        raise ValueError("bad config")

    cfg.redo = failing_redo
    ok = cfg.safe_reload()

    assert ok is False
    # Old config preserved
    assert cfg.result.data.foo == "bar"
    assert cfg.result.data.baz == "qux"

    # Fix and retry — deletion should now take effect
    cfg.redo = orig_redo
    ok2 = cfg.safe_reload()

    assert ok2 is True
    assert "foo" not in cfg.result.data
    assert cfg.result.data.baz == "qux"


def test_safe_reload_notgiven_no_leak_on_success():
    """After a successful safe_reload with NotGiven deletions, no
    NotGiven values leak into the result."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("a.x"), 1)
    cfg.mod(P("a.y"), 2)
    cfg.mod(P("b.z"), 3)
    cfg.redo()

    cfg.mod(P("a.x"), NotGiven)
    cfg.mod(P("b.z"), NotGiven)
    ok = cfg.safe_reload()

    assert ok is True
    assert not _has_notgiven(cfg.result)
    assert cfg.result.a.y == 2
    assert "x" not in cfg.result.a
    assert "z" not in cfg.result.b


def test_safe_reload_repeated_notgiven_deletions():
    """Repeated cycles of add/delete via safe_reload converge."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.counter"), 0)
    cfg.redo()

    for i in range(5):
        cfg.mod(P(f"data.item_{i}"), i)
        ok = cfg.safe_reload()
        assert ok is True
        assert cfg.result.data[f"item_{i}"] == i

    # Now delete alternating items
    for i in range(0, 5, 2):
        cfg.mod(P(f"data.item_{i}"), NotGiven)
        ok = cfg.safe_reload()
        assert ok is True

    assert "item_0" not in cfg.result.data
    assert cfg.result.data.item_1 == 1
    assert "item_2" not in cfg.result.data
    assert cfg.result.data.item_3 == 3
    assert "item_4" not in cfg.result.data
    assert cfg.result.data.counter == 0


# ── NotGiven convergence loop ───────────────────────────────────────


def test_notgiven_chained_deletion_converges():
    """Deleting a key that was added by a previous mod in the same
    args list converges through the redo loop."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.real"), "value")
    cfg.redo()

    # Add a new key and delete it in the same cycle
    cfg.mod(P("data.temp"), "ephemeral")
    cfg.mod(P("data.temp"), NotGiven)
    cfg.redo()

    assert "temp" not in cfg.result.data
    assert cfg.result.data.real == "value"
    assert not _has_notgiven(cfg.result)


def test_notgiven_does_not_corrupt_result():
    """The redo loop leaves no NotGiven sentinel in the final result."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("keep.this"), 42)
    cfg.mod(P("delete.me"), "gone")
    cfg.redo()

    cfg.mod(P("delete.me"), NotGiven)
    cfg.redo()

    # Walk the entire result to ensure no NotGiven leaked
    def _walk(d):
        if d is NotGiven:
            return True
        if isinstance(d, dict):
            return any(_walk(v) for v in d.values())
        if isinstance(d, (list, tuple)):
            return any(_walk(v) for v in d)
        return False

    assert not _walk(dict(cfg.result))
    assert cfg.result.keep.this == 42


def test_notgiven_readd_after_delete():
    """A key can be re-added after being deleted via NotGiven."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.flag"), True)
    cfg.redo()

    cfg.mod(P("data.flag"), NotGiven)
    cfg.redo()
    assert "flag" not in cfg.result.data

    cfg.mod(P("data.flag"), False)
    cfg.redo()
    assert cfg.result.data.flag is False


# ── CfgStore state isolation ────────────────────────────────────────


def test_safe_reload_restores_classvar_state():
    """safe_reload failure does not corrupt CfgStore.static or .env."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.x"), 1)
    cfg.redo()

    saved_static = copy.deepcopy(CfgStore.static)
    saved_env = copy.deepcopy(CfgStore.env)
    with suppress(KeyError):
        del saved_env.env["stdout"]

    orig_redo = cfg.redo

    def failing_redo() -> None:
        raise RuntimeError("boom")

    cfg.redo = failing_redo
    try:
        ok = cfg.safe_reload()
    finally:
        cfg.redo = orig_redo

    assert ok is False
    assert CfgStore.static == saved_static

    new_env = copy.deepcopy(CfgStore.env)
    with suppress(KeyError):
        del new_env.env["stdout"]
    assert new_env == saved_env
