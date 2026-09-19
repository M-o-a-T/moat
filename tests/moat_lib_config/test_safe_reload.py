"""Tests for safe config reload with fallback."""

from __future__ import annotations

import pytest
from unittest.mock import MagicMock

from moat.util import NotGiven, attrdict
from moat.lib.config import CfgStore
from moat.lib.path import P

# ── CfgStore.safe_reload ──────────────────────────────────────────────


def test_safe_reload_success():
    """safe_reload returns True and updates config on success."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.foo"), "bar")
    cfg.redo()

    assert cfg.result.data.foo == "bar"

    cfg.mod(P("data.foo"), "updated")
    ok = cfg.safe_reload()

    assert ok is True
    assert cfg.result.data.foo == "updated"


def test_safe_reload_fallback_on_exception():
    """safe_reload restores previous config when redo raises."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.value"), 42)
    cfg.redo()
    assert cfg.result.data.value == 42

    # Sabotage redo by replacing it with a failing stub.
    orig_redo = cfg.redo
    call_count = 0

    def failing_redo():
        nonlocal call_count
        call_count += 1
        raise ValueError("bad config")

    cfg.redo = failing_redo
    try:
        ok = cfg.safe_reload()
    finally:
        cfg.redo = orig_redo

    assert ok is False
    assert call_count == 1
    # Previous config preserved.
    assert cfg.result.data.value == 42


def test_safe_reload_preserves_state_on_failure():
    """safe_reload does not leave _redo or _updated in a dirty state."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.x"), "original")
    cfg.redo()

    saved_updated = cfg._updated  # noqa: SLF001

    def failing_redo():
        raise RuntimeError("boom")

    cfg.redo = failing_redo
    ok = cfg.safe_reload()

    assert ok is False
    assert cfg._redo is False  # noqa: SLF001
    assert cfg._updated == saved_updated  # noqa: SLF001
    assert cfg.result.data.x == "original"


def test_safe_reload_then_normal_redo():
    """After a failed safe_reload, a subsequent normal redo works."""
    cfg = CfgStore(name=None, load_all=None, preload=attrdict(env=NotGiven))
    cfg.mod(P("data.v"), 1)
    cfg.redo()

    fail = True

    def maybe_fail_redo():
        if fail:
            raise ValueError("nope")
        CfgStore.redo(cfg)

    cfg.redo = maybe_fail_redo
    ok = cfg.safe_reload()
    assert ok is False

    # Now fix the problem and reload normally.
    cfg.redo = lambda: CfgStore.redo(cfg)
    cfg.mod(P("data.v"), 2)
    cfg.redo()
    assert cfg.result.data.v == 2


# ── DirCmd.safe_reload ────────────────────────────────────────────────


@pytest.mark.anyio
async def test_dir_cmd_safe_reload_restores_detached_apps():
    """DirCmd.safe_reload restores sub-apps detached during a failed reload."""
    from moat.lib.micro import Lock  # noqa: PLC0415
    from moat.lib.rpc.cmd.tree._dir import DirCmd  # noqa: PLC0415

    cmd = DirCmd.__new__(DirCmd)
    cmd.sub = {}
    cmd._lock = Lock()  # noqa: SLF001
    cmd.cfg = attrdict()
    cmd._parent = None  # noqa: SLF001
    cmd._name = None  # noqa: SLF001

    # Simulate two existing sub-apps.
    app_a = MagicMock()
    app_b = MagicMock()
    cmd.sub = {"a": app_a, "b": app_b}

    # Track detach/attach calls.
    detached = []

    async def fake_attach(name, app):
        if app is not None:
            cmd.sub[name] = app
        else:
            cmd.sub.pop(name, None)

    async def fake_detach(name):
        detached.append(name)
        cmd.sub.pop(name, None)

    cmd.attach = fake_attach
    cmd.detach = fake_detach

    # Make super().reload() detach "a" then fail.
    async def failing_super_reload(self):
        await self.detach("a")  # simulate partial teardown

    async def failing_setup_apps(self):  # noqa: ARG001
        raise RuntimeError("bad app config")

    # Monkeypatch the superclass methods.
    from moat.lib.rpc.cmd.tree import _dir as dir_mod  # noqa: PLC0415

    orig_reload = dir_mod.BaseSubCmd.reload
    orig_setup = DirCmd._setup_apps  # noqa: SLF001

    dir_mod.BaseSubCmd.reload = failing_super_reload
    DirCmd._setup_apps = failing_setup_apps  # noqa: SLF001
    try:
        ok = await cmd.safe_reload()
    finally:
        dir_mod.BaseSubCmd.reload = orig_reload
        DirCmd._setup_apps = orig_setup  # noqa: SLF001

    assert ok is False
    # "a" was detached during the failed reload, then restored.
    assert "a" in cmd.sub
    assert "b" in cmd.sub
    # The restored app is the original object.
    assert cmd.sub["a"] is app_a


@pytest.mark.anyio
async def test_dir_cmd_safe_reload_removes_newly_created_apps():
    """DirCmd.safe_reload detaches apps created during a failed reload."""
    from moat.lib.micro import Lock  # noqa: PLC0415
    from moat.lib.rpc.cmd.tree._dir import DirCmd  # noqa: PLC0415

    cmd = DirCmd.__new__(DirCmd)
    cmd.sub = {}
    cmd._lock = Lock()  # noqa: SLF001
    cmd.cfg = attrdict()
    cmd._parent = None  # noqa: SLF001
    cmd._name = None  # noqa: SLF001

    app_original = MagicMock()
    cmd.sub = {"orig": app_original}

    detached = []

    async def fake_attach(name, app):
        cmd.sub[name] = app

    async def fake_detach(name):
        detached.append(name)
        cmd.sub.pop(name, None)

    cmd.attach = fake_attach
    cmd.detach = fake_detach

    new_app = MagicMock()

    async def failing_super_reload(self):
        # Simulate adding a new app during reload.
        await self.attach("new", new_app)

    async def failing_setup_apps(self):  # noqa: ARG001
        raise RuntimeError("boom")

    from moat.lib.rpc.cmd.tree import _dir as dir_mod  # noqa: PLC0415

    orig_reload = dir_mod.BaseSubCmd.reload
    orig_setup = DirCmd._setup_apps  # noqa: SLF001

    dir_mod.BaseSubCmd.reload = failing_super_reload
    DirCmd._setup_apps = failing_setup_apps  # noqa: SLF001
    try:
        ok = await cmd.safe_reload()
    finally:
        dir_mod.BaseSubCmd.reload = orig_reload
        DirCmd._setup_apps = orig_setup  # noqa: SLF001

    assert ok is False
    # The newly-created app was cleaned up.
    assert "new" not in cmd.sub
    assert "new" in detached
    # Original app still present.
    assert "orig" in cmd.sub


# ── BaseSubCmd.safe_reload ────────────────────────────────────────────


@pytest.mark.anyio
async def test_base_sub_cmd_safe_reload_per_app_fallback():
    """BaseSubCmd.safe_reload continues on sub-app failure."""
    from moat.lib.micro import Lock  # noqa: PLC0415
    from moat.lib.rpc.cmd.tree._dir import BaseSubCmd  # noqa: PLC0415

    cmd = BaseSubCmd.__new__(BaseSubCmd)
    cmd.sub = {}
    cmd._lock = Lock()  # noqa: SLF001
    cmd.cfg = attrdict()
    cmd._parent = None  # noqa: SLF001
    cmd._name = None  # noqa: SLF001

    class FakeRoot:
        def cfg_reloaded(self, cfg):
            pass

    cmd.root = FakeRoot()

    class GoodApp:
        async def reload(self):
            self.reloaded = True

    class BadApp:
        async def reload(self):
            raise RuntimeError("broken")

    good = GoodApp()
    bad = BadApp()
    cmd.sub = {"good": good, "bad": bad}

    # BaseSuperCmd.reload is a no-op; super().reload() does nothing.
    ok = await cmd.safe_reload()

    assert ok is False
    assert good.reloaded is True


# ── RootCmd.safe_reload ──────────────────────────────────────────────


@pytest.mark.anyio
async def test_root_cmd_safe_reload_delegates_to_app():
    """RootCmd.safe_reload delegates to app.safe_reload when available."""
    from moat.lib.rpc.cmd._base import RootCmd  # noqa: PLC0415

    root = RootCmd.__new__(RootCmd)

    class FakeApp:
        def __init__(self):
            self.reload_called = False
            self.safe_reload_called = False

        async def safe_reload(self):
            self.safe_reload_called = True
            return True

        async def reload(self):
            self.reload_called = True

    app = FakeApp()
    root.app = app
    root._updates = {}  # noqa: SLF001

    ok = await root.safe_reload()

    assert ok is True
    assert app.safe_reload_called is True
    assert app.reload_called is False


@pytest.mark.anyio
async def test_root_cmd_safe_reload_fallback_to_plain_reload():
    """RootCmd.safe_reload falls back to plain reload if no safe_reload."""
    from moat.lib.rpc.cmd._base import RootCmd  # noqa: PLC0415

    root = RootCmd.__new__(RootCmd)

    class FakeApp:
        def __init__(self):
            self.reload_called = False

        async def reload(self):
            self.reload_called = True

    app = FakeApp()
    root.app = app
    root._updates = {}  # noqa: SLF001

    ok = await root.safe_reload()

    assert ok is True
    assert app.reload_called is True


@pytest.mark.anyio
async def test_root_cmd_safe_reload_handles_app_none():
    """RootCmd.safe_reload returns False when app is None."""
    from moat.lib.rpc.cmd._base import RootCmd  # noqa: PLC0415

    root = RootCmd.__new__(RootCmd)
    root.app = None

    ok = await root.safe_reload()
    assert ok is False


@pytest.mark.anyio
async def test_root_cmd_safe_reload_catches_app_failure():
    """RootCmd.safe_reload returns False when app.reload raises."""
    from moat.lib.rpc.cmd._base import RootCmd  # noqa: PLC0415

    root = RootCmd.__new__(RootCmd)

    class FailingApp:
        async def reload(self):
            raise RuntimeError("broken")

    root.app = FailingApp()
    root._updates = {}  # noqa: SLF001

    ok = await root.safe_reload()
    assert ok is False


@pytest.mark.anyio
async def test_root_cmd_safe_reload_catches_safe_reload_failure():
    """RootCmd.safe_reload returns False when app.safe_reload raises."""
    from moat.lib.rpc.cmd._base import RootCmd  # noqa: PLC0415

    root = RootCmd.__new__(RootCmd)

    class FailingSafeApp:
        async def safe_reload(self):
            raise RuntimeError("safe_reload broken")

    root.app = FailingSafeApp()
    root._updates = {}  # noqa: SLF001

    ok = await root.safe_reload()
    assert ok is False
