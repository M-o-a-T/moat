"""End-to-end tests for ``moat.link.job`` CLI commands.

Each test runs the full ``moat link job ...`` decorator stack through
:py:meth:`moat.link._test.Scaffold.run` and verifies the resulting
state in the MoaT-Link tree.
"""

from __future__ import annotations

import pytest
import time

import asyncclick as click

import moat.link.job  # noqa:F401 - register cfg
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.src.test import raises

pytestmark = pytest.mark.anyio


async def test_set_get_delete(cfg):
    """Add, read, then delete a job record via the CLI."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.job.prefix
        sub = cfg.link.job.sub.group + P("default")

        # Create a job.
        await sf.run(
            "link job at foo set -c test.greet -t 0 -i greet -v who there",
        )
        await c.i_sync()

        stored = await c.d_get(prefix + sub + P("foo"))
        assert stored["code"] == P("test.greet")
        assert stored["info"] == "greet"
        assert stored["data"] == {"who": "there"}
        # target=0 means "now"; we passed "-t 0" so the entry should
        # have target set close to current time.
        assert stored["target"] is not None
        assert abs(stored["target"] - time.time()) < 5

        # Read it back via the CLI.
        r = await sf.run("link job at foo get")
        assert "test.greet" in r.stdout
        assert "there" in r.stdout

        # The 'path' subcommand prints both control and state paths.
        r = await sf.run("link job at foo path")
        assert "job.any.default.foo" in r.stdout
        assert "run.job.any.default.foo" in r.stdout

        # Delete it (force=true since we set a non-None target).
        await sf.run("link job at foo delete -f")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + sub + P("foo"))


async def test_set_with_copy(cfg):
    """``--copy`` clones an existing entry as a template."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.job.prefix
        sub = cfg.link.job.sub.group + P("default")

        # Create the original.
        await sf.run("link job at orig set -c test.greet -i original -v who alice")
        await c.i_sync()

        # Clone it under a new name.
        full_orig_path = prefix + sub + P("orig")
        await sf.run(
            ("link", "job", "at", "clone", "set", "-C", str(full_orig_path), "-v", "who", "bob"),
        )
        await c.i_sync()

        clone = await c.d_get(prefix + sub + P("clone"))
        assert clone["code"] == P("test.greet")
        # The cloned entry keeps the original's info but applies new vars.
        assert clone["info"] == "original"
        assert clone["data"]["who"] == "bob"


async def test_list_table(cfg):
    """The CLI ``list -t`` command produces one-line summaries."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await sf.run("link job at one set -c code.one -t -")
        await sf.run("link job at two set -c code.two -t -")
        await c.i_sync()

        r = await sf.run("link job at : list -t")
        assert "one" in r.stdout
        assert "two" in r.stdout
        # We never started anything so each row is "-never-".
        assert r.stdout.count("-never-") == 2


async def test_info_lists_groups(cfg):
    """``info`` lists the groups (or hosts) below the current root."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        # Make sure two groups exist below the AnyRunner prefix.
        await sf.run("link job -g groupA at foo set -c x -t -")
        await sf.run("link job -g groupB at bar set -c x -t -")
        await c.i_sync()

        r = await sf.run("link job info")
        assert "groupA" in r.stdout
        assert "groupB" in r.stdout


async def test_node_modes_use_distinct_paths(cfg):
    """``-n NODE`` selects single-node layout; ``-n -`` selects all-nodes layout."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.job.prefix
        sub_grp = cfg.link.job.sub.group + P("default")
        sub_at = cfg.link.job.sub.single + P("node1") + P("default")
        sub_all = cfg.link.job.sub["all"] + P("default")

        await sf.run("link job at any_foo set -c x -t -")
        await sf.run("link job -n node1 at single_foo set -c x -t -")
        await sf.run("link job -n - at all_foo set -c x -t -")
        await c.i_sync()

        assert (await c.d_get(prefix + sub_grp + P("any_foo")))["code"] == P("x")
        assert (await c.d_get(prefix + sub_at + P("single_foo")))["code"] == P("x")
        assert (await c.d_get(prefix + sub_all + P("all_foo")))["code"] == P("x")


async def test_debug_runs_job(cfg):
    """``moat link job at FOO debug`` runs the snippet once with overrides."""
    from moat.link.code import CODE_EXEC_ROOT  # noqa: PLC0415

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.job.prefix
        state = cfg.link.job.state
        sub = cfg.link.job.sub.group + P("default")

        # A snippet that just echoes its 'who' parameter.
        await c.d_set(
            CODE_EXEC_ROOT + P("test.greet"),
            dict(code="return 'hi ' + who", vars=dict(who="world"), is_async=True),
        )
        await sf.run("link job at d1 set -c test.greet -t 0 -v who default")
        await c.i_sync()

        # Override 'who' on the fly via ``-v``.
        r = await sf.run("link job at d1 debug -v who alice")
        assert "hi alice" in r.stdout

        # The stored job's ``data`` is untouched.
        stored = await c.d_get(prefix + sub + P("d1"))
        assert stored["data"]["who"] == "default"

        # A state record with the link connection ID is left behind.
        st = await c.d_get(state + sub + P("d1"))
        assert st["started"] > 0
        assert st["stopped"] >= st["started"]
        # node is cleared after the run finishes cleanly.
        assert st["node"] is None


async def test_debug_refuses_running_owner(cfg):
    """``debug`` aborts when another runner currently owns the job."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        from moat.link.code import CODE_EXEC_ROOT  # noqa: PLC0415

        state = cfg.link.job.state
        sub = cfg.link.job.sub.group + P("default")

        # A do-nothing snippet so ``-f`` actually succeeds.
        await c.d_set(
            CODE_EXEC_ROOT + P("test.noop"),
            dict(code="return None", is_async=True),
        )
        await sf.run("link job at busy set -c test.noop -t -")

        # Pretend a different runner is currently running the job.
        await c.d_set(
            state + sub + P("busy"),
            dict(started=time.time(), stopped=0, node="other_node", backoff=0),
            retain=True,
        )
        await c.i_sync()

        # Without ``-f`` the command refuses.
        with raises(click.exceptions.UsageError) as r:
            await sf.run("link job at busy debug")
        assert "already running" in str(r.value)

        # With ``-f`` the command succeeds and overwrites state.node.
        await sf.run("link job at busy debug -f")
        await c.i_sync()
        st = await c.d_get(state + sub + P("busy"))
        assert st["node"] is None  # cleared after the forced run


async def test_debug_logs_to_stderr(cfg, capfd):
    """``_log`` output from the snippet goes to stderr at DEBUG level."""
    from moat.link.code import CODE_EXEC_ROOT  # noqa: PLC0415

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(
            CODE_EXEC_ROOT + P("test.chatty"),
            dict(
                code="_log.debug('HELLO-DEBUG'); _log.info('HELLO-INFO'); return None",
                is_async=True,
            ),
        )
        await sf.run("link job at chatty set -c test.chatty -t -")

        # ``capfd`` snapshots fd-level stderr; clear the prior buffer so
        # we only see the debug invocation's output.
        capfd.readouterr()
        await sf.run("link job at chatty debug")
        captured = capfd.readouterr()
        assert "HELLO-DEBUG" in captured.err
        assert "HELLO-INFO" in captured.err


async def test_debug_takes_over_dead_anon_owner(cfg):
    """``debug`` reclaims a job stuck on a vanished anonymous client."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        from moat.link.code import CODE_EXEC_ROOT  # noqa: PLC0415

        state = cfg.link.job.state
        sub = cfg.link.job.sub.group + P("default")

        await c.d_set(
            CODE_EXEC_ROOT + P("test.noop"),
            dict(code="return None", is_async=True),
        )
        await sf.run("link job at zombie set -c test.noop -t -")

        # The previous owner has an auto-generated id (leading ``_``) and
        # is no longer connected to the server.
        await c.d_set(
            state + sub + P("zombie"),
            dict(started=time.time(), stopped=0, node="_dead_client", backoff=0),
            retain=True,
        )
        await c.i_sync()

        # Should run without ``-f``: liveness check finds nothing.
        await sf.run("link job at zombie debug")
        await c.i_sync()
        st = await c.d_get(state + sub + P("zombie"))
        assert st["node"] is None


async def test_debug_refuses_live_anon_owner(cfg):
    """``debug`` refuses if the anonymous owner is still connected."""
    from moat.link.client import Link  # noqa: PLC0415

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        # Connect a *second* client without a fixed name so that the
        # server assigns it an auto-generated (``_``-prefixed) ID.
        other_cli = Link(sf.cfg)  # no name -> _xxxxxx
        async with sf.client_(cli=other_cli) as other:
            assert other.id.startswith("_")

            state = cfg.link.job.state
            sub = cfg.link.job.sub.group + P("default")

            await sf.run("link job at live set -c test.noop -t -")
            await c.d_set(
                state + sub + P("live"),
                dict(started=time.time(), stopped=0, node=other.id, backoff=0),
                retain=True,
            )
            await c.i_sync()

            with raises(click.exceptions.UsageError) as r:
                await sf.run("link job at live debug")
            assert "already running" in str(r.value)
