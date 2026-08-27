"""Tests for error-to-notification mirroring."""

from __future__ import annotations

import anyio
import pytest

from moat.util import NotGiven, to_attrdict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.link.notify import ErrorMirror

pytestmark = pytest.mark.anyio


def _mirror_cfg(**extra) -> to_attrdict:
    """Build a notify config with the given overrides."""
    cfg = to_attrdict({
        "path": P("notify"),
    })
    cfg.update(extra)
    return cfg


async def _wait_for_notify(reader, path: str, timeout: float = 5) -> dict:
    """Poll d_get until a notification appears at *path*."""
    with anyio.fail_after(timeout):
        while True:
            try:
                data = await reader.d_get(P(path))
            except (KeyError, ValueError):
                pass
            else:
                if data is not NotGiven:
                    return data
            await anyio.sleep(0.1)


async def _wait_for_clear(reader, path: str, timeout: float = 5) -> None:
    """Poll d_get until the notification at *path* is gone."""
    with anyio.fail_after(timeout):
        while True:
            try:
                data = await reader.d_get(P(path))
            except (KeyError, ValueError):
                return
            if data is NotGiven:
                return
            await anyio.sleep(0.1)


async def test_mirror_default(cfg):
    """An error above the default threshold is mirrored to notify.*."""
    cfg.link.notify = _mirror_cfg()

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as reader,
    ):
        evt = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(ErrorMirror(cfg.link.notify).run, reader, evt)
            await evt.wait()

            await writer.d_set(
                P("error.run.host.demo"),
                {"msg": "host down", "level": 4},
            )
            await writer.i_sync()

            data = await _wait_for_notify(reader, "notify.run.host.demo")
            assert data["msg"] == "host down"
            assert data["prio"] == "error"
            assert data["title"] == "run.host.demo"

            tg.cancel_scope.cancel()


async def test_mirror_clears_when_resolved(cfg):
    """An error resolution clears the mirrored notification."""
    cfg.link.notify = _mirror_cfg()

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as reader,
    ):
        evt = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(ErrorMirror(cfg.link.notify).run, reader, evt)
            await evt.wait()

            await writer.d_set(
                P("error.run.host.demo"),
                {"msg": "host down", "level": 4},
            )
            await writer.i_sync()

            data = await _wait_for_notify(reader, "notify.run.host.demo")
            assert data["msg"] == "host down"

            await writer.d_set(P("error.run.host.demo"), NotGiven)
            await writer.i_sync()

            await _wait_for_clear(reader, "notify.run.host.demo")

            tg.cancel_scope.cancel()


async def test_mirror_clears_when_ok(cfg):
    """An error marked ok=True clears the mirrored notification."""
    cfg.link.notify = _mirror_cfg()

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as reader,
    ):
        evt = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(ErrorMirror(cfg.link.notify).run, reader, evt)
            await evt.wait()

            await writer.d_set(
                P("error.run.host.demo"),
                {"msg": "host down", "level": 4},
            )
            await writer.i_sync()

            data = await _wait_for_notify(reader, "notify.run.host.demo")
            assert data["msg"] == "host down"

            await writer.d_set(
                P("error.run.host.demo"),
                {"msg": "host down", "level": 4, "ok": True},
            )
            await writer.i_sync()

            await _wait_for_clear(reader, "notify.run.host.demo")

            tg.cancel_scope.cancel()


async def test_mirror_filters_below_default_threshold(cfg):
    """Errors below the default threshold (warning) are not mirrored."""
    cfg.link.notify = _mirror_cfg()

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as reader,
    ):
        evt = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(ErrorMirror(cfg.link.notify).run, reader, evt)
            await evt.wait()

            # level 2 = info, below default threshold (warning=3)
            await writer.d_set(
                P("error.run.host.low"),
                {"msg": "minor issue", "level": 2},
            )
            await writer.i_sync()
            await anyio.sleep(0.3)

            try:
                data = await reader.d_get(P("notify.run.host.low"))
                assert data is NotGiven, "Below-threshold error was mirrored"
            except (KeyError, ValueError):
                pass

            # level 4 = error, above threshold — should be mirrored
            await writer.d_set(
                P("error.run.host.high"),
                {"msg": "major issue", "level": 4},
            )
            await writer.i_sync()

            data = await _wait_for_notify(reader, "notify.run.host.high")
            assert data["msg"] == "major issue"

            tg.cancel_scope.cancel()


async def test_mirror_with_vecs_min_level(cfg):
    """A notify-vecs tree can override the minimum severity."""
    cfg.link.notify = _mirror_cfg(vecs=P("notify_rules"))

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as reader,
    ):
        # Set up a notify-vecs tree: root rule requires 'error' (level 4).
        await writer.d_set(
            P("conv.notify_rules"),
            {"min_level": "error"},
        )
        await writer.i_sync()

        evt = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(ErrorMirror(cfg.link.notify).run, reader, evt)
            await evt.wait()

            # Warning (level 3) — below the vecs threshold of 'error' (4)
            await writer.d_set(
                P("error.run.host.warn"),
                {"msg": "warning issue", "level": 3},
            )
            await writer.i_sync()
            await anyio.sleep(0.3)

            try:
                data = await reader.d_get(P("notify.run.host.warn"))
                assert data is NotGiven, "Below-vecs-threshold error was mirrored"
            except (KeyError, ValueError):
                pass

            # Error (level 4) — meets the vecs threshold
            await writer.d_set(
                P("error.run.host.err"),
                {"msg": "real error", "level": 4},
            )
            await writer.i_sync()

            data = await _wait_for_notify(reader, "notify.run.host.err")
            assert data["msg"] == "real error"

            tg.cancel_scope.cancel()


async def test_mirror_with_vecs_skip(cfg):
    """A notify-vecs tree can skip specific error paths."""
    cfg.link.notify = _mirror_cfg(vecs=P("notify_rules"))

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as reader,
    ):
        # Skip errors under run.notify.*
        await writer.d_set(
            P("conv.notify_rules.run.notify"),
            {"skip": True},
        )
        await writer.i_sync()

        evt = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(ErrorMirror(cfg.link.notify).run, reader, evt)
            await evt.wait()

            await writer.d_set(
                P("error.run.notify.backend"),
                {"msg": "backend fail", "level": 4},
            )
            await writer.i_sync()
            await anyio.sleep(0.3)

            try:
                data = await reader.d_get(P("notify.run.notify.backend"))
                assert data is NotGiven, "Skipped error was mirrored"
            except (KeyError, ValueError):
                pass

            await writer.d_set(
                P("error.run.host.demo"),
                {"msg": "host down", "level": 4},
            )
            await writer.i_sync()

            data = await _wait_for_notify(reader, "notify.run.host.demo")
            assert data["msg"] == "host down"

            tg.cancel_scope.cancel()


async def test_mirror_with_vecs_hierarchy(cfg):
    """More-specific vecs branches override less-specific ones via Node.collect."""
    cfg.link.notify = _mirror_cfg(vecs=P("notify_rules"))

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as reader,
    ):
        # Root rule: min_level = warning (3)
        await writer.d_set(
            P("conv.notify_rules"),
            {"min_level": "warning"},
        )
        # More specific rule for run.host: min_level = error (4)
        await writer.d_set(
            P("conv.notify_rules.run.host"),
            {"min_level": "error"},
        )
        await writer.i_sync()

        evt = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(ErrorMirror(cfg.link.notify).run, reader, evt)
            await evt.wait()

            # Warning (3) under run.host — overridden to 'error'(4), should be skipped
            await writer.d_set(
                P("error.run.host.demo"),
                {"msg": "warn on host", "level": 3},
            )
            await writer.i_sync()
            await anyio.sleep(0.3)

            try:
                data = await reader.d_get(P("notify.run.host.demo"))
                assert data is NotGiven, "Overridden-threshold error was mirrored"
            except (KeyError, ValueError):
                pass

            # Warning (3) under run.other — uses root rule (warning=3), should be mirrored
            await writer.d_set(
                P("error.run.other.demo"),
                {"msg": "warn elsewhere", "level": 3},
            )
            await writer.i_sync()

            data = await _wait_for_notify(reader, "notify.run.other.demo")
            assert data["msg"] == "warn elsewhere"
            assert data["prio"] == "warning"

            tg.cancel_scope.cancel()


async def test_mirror_with_vecs_title_override(cfg):
    """A notify-vecs tree can override the notification title."""
    cfg.link.notify = _mirror_cfg(vecs=P("notify_rules"))

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as reader,
    ):
        await writer.d_set(
            P("conv.notify_rules.run.host"),
            {"title": "Custom Host Alert"},
        )
        await writer.i_sync()

        evt = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(ErrorMirror(cfg.link.notify).run, reader, evt)
            await evt.wait()

            await writer.d_set(
                P("error.run.host.demo"),
                {"msg": "host down", "level": 4},
            )
            await writer.i_sync()

            data = await _wait_for_notify(reader, "notify.run.host.demo")
            assert data["msg"] == "host down"
            assert data["title"] == "Custom Host Alert"

            tg.cancel_scope.cancel()


async def test_mirror_handles_non_dict_data(cfg):
    """Non-dict error data is converted to a string message."""
    cfg.link.notify = _mirror_cfg()

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as reader,
    ):
        evt = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(ErrorMirror(cfg.link.notify).run, reader, evt)
            await evt.wait()

            await writer.d_set(
                P("error.run.host.strange"),
                "simple string error",
            )
            await writer.i_sync()

            data = await _wait_for_notify(reader, "notify.run.host.strange")
            assert data["msg"] == "simple string error"

            tg.cancel_scope.cancel()


async def test_mirror_with_vecs_prio_override(cfg):
    """A notify-vecs tree can override the notification priority."""
    cfg.link.notify = _mirror_cfg(vecs=P("notify_rules"))

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as writer,
        sf.client_() as reader,
    ):
        await writer.d_set(
            P("conv.notify_rules.run.host"),
            {"prio": "fatal"},
        )
        await writer.i_sync()

        evt = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(ErrorMirror(cfg.link.notify).run, reader, evt)
            await evt.wait()

            # Even though level=4 (error), the vecs override forces prio=fatal
            await writer.d_set(
                P("error.run.host.demo"),
                {"msg": "host down", "level": 4},
            )
            await writer.i_sync()

            data = await _wait_for_notify(reader, "notify.run.host.demo")
            assert data["msg"] == "host down"
            assert data["prio"] == "fatal"

            tg.cancel_scope.cancel()
