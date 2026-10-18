"""End-to-end tests for ``moat.link.job`` CLI commands.

Each test runs the full ``moat link job ...`` decorator stack through
:py:meth:`moat.link._test.Scaffold.run` and verifies the resulting
state in the MoaT-Link tree.
"""

from __future__ import annotations

import anyio
import pytest
import time

import asyncclick as click

import moat.link.job  # noqa:F401 - register cfg
from moat.util import attrdict, combine_dict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.src.test import raises

pytestmark = pytest.mark.anyio


async def _wait_state(c, state_path, *, timeout: float = 15, until=None):
    """Poll ``state_path`` until it satisfies ``until``."""
    if until is None:

        def _ok(_st):
            return bool(_st)

        until = _ok
    with anyio.fail_after(timeout):
        while True:
            try:
                st = await c.d_get(state_path)
            except KeyError:
                st = None
            if isinstance(st, dict) and until(st):
                return st
            await anyio.sleep(0.1)


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


async def test_error_state(cfg):
    """A stopped job with an open error is "-error-"; ``get -e`` shows it."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.job.prefix
        state = cfg.link.job.state
        sub = cfg.link.job.sub.group + P("default")

        await sf.run("link job at bad set -c code.bad -t -")
        await sf.run("link job at fine set -c code.fine -t -")
        now = time.time()
        for n in ("bad", "fine"):
            await c.d_set(
                state + sub + P(n),
                dict(started=now - 2, stopped=now - 1, node=None, backoff=1),
                retain=True,
            )
        await c.e_exc(prefix + sub + P("bad"), RuntimeError("boom"))
        await c.i_sync()

        r = await sf.run("link job at : list -t")
        rows = {ln.split()[0]: ln for ln in r.stdout.splitlines() if ln.strip()}
        assert "-error-" in rows["bad"]
        # stopped 1s ago, delay 100 * 1.1 ** 1
        assert "retry in" in rows["bad"]
        assert "-stopped-" in rows["fine"]

        r = await sf.run("link job at : list -t -N")
        assert "bad" in r.stdout
        assert "fine" not in r.stdout
        r = await sf.run("link job at : list -t -e")
        assert "boom" in r.stdout
        r = await sf.run("link job at : list -e")
        assert r.stdout.count("error:") == 1
        r = await sf.run("link job at : list -s")
        assert r.stdout.count("state:") == 2
        r = await sf.run("link job at : list -N")
        assert "bad" in r.stdout
        assert "fine" not in r.stdout

        r = await sf.run("link job at bad get -e")
        assert "error:" in r.stdout
        r = await sf.run("link job at fine get -e")
        assert "error:" not in r.stdout


async def test_list_table_many(cfg):
    """``list -t`` over a larger subtree must not deadlock.

    Regression test: fetching each job's state inline while still
    iterating the walking stream deadlocked once the walk's flow-control
    window filled, because the consumer blocked in a ``d.get`` call and
    stopped advancing credit to the server.  Using more jobs than the
    stream's receive-window (plus a handful of nested sub-paths) is
    enough to reproduce the original hang.
    """
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        # Plenty of jobs, spread across nested paths, exceeding the
        # walk stream's receive window (default 20).
        for i in range(40):
            grp = "grp" + str(i // 10)
            await sf.run(f"link job at {grp}.job{i} set -c code.x -t -")
        await c.i_sync()

        r = await sf.run("link job at : list -t")
        # Every job shows up, each marked "-never-" since nothing ran.
        assert r.stdout.count("-never-") == 40
        assert "grp0.job0" in r.stdout
        assert "grp3.job39" in r.stdout


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
            dict(
                code="return 'hi ' + who", vars=["who"], default=dict(who="world"), is_async=True
            ),
        )
        await sf.run("link job at d1 set -c test.greet -t 0 -v who default")
        await c.i_sync()

        # Override 'who' on the fly via ``-v``.
        r = await sf.run("link job at d1 debug -v who alice")
        assert "hi alice" in r.stdout
        await c.i_sync()

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

        # Pretend the currently-connected client ``c`` is running the
        # job.  Its ID is known to the server, so ``is_client_alive``
        # will confirm liveness and ``debug`` will refuse without -f.
        await c.d_set(
            state + sub + P("busy"),
            dict(started=time.time(), stopped=0, node=c.id, backoff=0),
            retain=True,
        )
        await c.i_sync()

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
        await c.i_sync()

        # ``capfd`` snapshots fd-level stderr; clear the prior buffer so
        # we only see the debug invocation's output.
        capfd.readouterr()
        await sf.run("link job at chatty debug")
        captured = capfd.readouterr()
        assert "HELLO-DEBUG" in captured.err
        assert "HELLO-INFO" in captured.err


async def test_debug_takes_over_dead_owner(cfg):
    """``debug`` reclaims a job whose owner is no longer connected."""
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

        # The previous owner is no longer connected to the server.
        await c.d_set(
            state + sub + P("zombie"),
            dict(started=time.time(), stopped=0, node="dead_client", backoff=0),
            retain=True,
        )
        await c.i_sync()

        # Should run without ``-f``: liveness probe finds nothing.
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


async def test_set_stops_running_job(cfg):
    """Modifying a running job's record via the CLI stops it.

    A data-only change parks the job; ``set -t0`` (re)starts it. Both
    in one command stops and restarts it.
    """
    from moat.link.code import CODE_EXEC_ROOT  # noqa: PLC0415
    from moat.link.job import AnyJobRunner  # noqa: PLC0415

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(
            CODE_EXEC_ROOT + P("test.cli_sleep"),
            dict(
                code="""
import anyio
await _self.setup_done()
await anyio.sleep_forever()
""",
                is_async=True,
            ),
        )
        job_cfg = combine_dict(attrdict(actor=attrdict(cycle=1, gap=0.2)), cfg.link["job"])
        sub = job_cfg["sub"]["group"] + P("default")
        state_path = job_cfg["state"] + sub + P("clij")

        await sf.run("link job at clij set -c test.cli_sleep -t0")
        await c.i_sync()

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            st0 = await _wait_state(
                c, state_path, until=lambda s: s.get("node") == c.name and not s.get("stopped")
            )

            # Data-only change: the job stops and stays stopped.
            await sf.run("link job at clij set -v x 1")
            await c.i_sync()
            st = await _wait_state(c, state_path, until=lambda s: s.get("stopped", 0) > 0)
            assert st["started"] == st0["started"]
            await anyio.sleep(1)
            st = await c.d_get(state_path)
            assert st.get("stopped", 0) > 0  # still parked

            # ``-t0`` restarts it.
            await sf.run("link job at clij set -t0")
            await c.i_sync()
            st = await _wait_state(
                c, state_path, until=lambda s: s.get("started", 0) > st0["started"]
            )
            assert st["node"] == c.name

            # Data change and ``-t0`` in one command: stop + restart.
            st1 = st
            await sf.run("link job at clij set -v x 2 -t0")
            await c.i_sync()
            st = await _wait_state(
                c, state_path, until=lambda s: s.get("started", 0) > st1["started"]
            )
            assert st["node"] == c.name
            tg.cancel_scope.cancel()
