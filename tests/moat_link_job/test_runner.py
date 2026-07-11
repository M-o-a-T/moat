"""End-to-end tests for the ``moat.link.job`` runner.

Each test sets up a Scaffold + server + client, stores a code snippet
and one or more job records, starts a runner, and verifies behaviour
through the dynamic state path.
"""

from __future__ import annotations

import anyio
import pytest
import time

import moat.link.job  # noqa:F401 - register cfg
from moat.util import NotGiven, attrdict, combine_dict
from moat.lib.path import P, Root
from moat.link._test import Scaffold
from moat.link.code import CODE_EXEC_ROOT
from moat.link.job import (
    JOB_ROOT_DEFAULT,
    STATE_ROOT_DEFAULT,
    AllJobRunner,
    AnyJobRunner,
    SingleJobRunner,
)

from typing import Any

pytestmark = pytest.mark.anyio


def _job_cfg(sf: Scaffold) -> attrdict:
    """Return a job-runner config with a fast actor cycle for tests."""
    return combine_dict(
        attrdict(actor=attrdict(cycle=1, gap=0.2)),
        sf.cfg["job"],
        cls=attrdict,
    )


async def _wait_state(
    c: Any,
    state_path: P,
    *,
    timeout: float = 15,
    until: Any = None,
) -> dict[str, Any]:
    """Poll ``state_path`` until the state record matches ``until``.

    Args:
        c: a connected MoaT-Link client.
        state_path: where the state record will appear.
        timeout: outer fail-after, in seconds.
        until: predicate ``state -> bool`` to wait for.

    Returns:
        The first state record that satisfied ``until``.
    """
    if until is None:

        def _ok(_st: dict[str, Any] | None) -> bool:
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


async def test_defaults_match_cfg(cfg):
    "The module-level path defaults equal the config keys."
    assert P("job") == JOB_ROOT_DEFAULT
    assert P("run.job") == STATE_ROOT_DEFAULT
    job_cfg = cfg.link["job"]
    assert job_cfg["prefix"] == JOB_ROOT_DEFAULT
    assert job_cfg["state"] == STATE_ROOT_DEFAULT


async def test_anyrunner_simple_job(cfg):
    "End-to-end: AnyJobRunner picks up a single job, runs it, records state."
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "world!"}),
        sf.client_() as c,
    ):
        await c.d_set(
            CODE_EXEC_ROOT + P("test.greet"),
            dict(
                code="return 'hi ' + who", vars=["who"], default=dict(who="world"), is_async=True
            ),
        )

        job_cfg = _job_cfg(sf)
        sub = job_cfg["sub"]["group"] + P("default")
        job_path = job_cfg["prefix"] + sub + P("greet")
        state_path = job_cfg["state"] + sub + P("greet")

        await c.d_set(
            job_path,
            dict(
                code=P("test.greet"),
                data=dict(who="there"),
                target=time.time(),
                repeat=0,
                delay=100,
                backoff=1.1,
            ),
        )
        await c.i_sync()

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            st = await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("result") == "hi there",
            )
            assert st["node"] is None or st["stopped"] > 0
            tg.cancel_scope.cancel()


async def test_singlerunner_specific_node(cfg):
    "SingleJobRunner runs jobs scoped to one named node."
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(
            CODE_EXEC_ROOT + P("test.answer"),
            dict(code="return 42", is_async=True),
        )

        job_cfg = _job_cfg(sf)
        # SingleRunner's subpath layout is sub.single / NODE / GROUP.
        sub = job_cfg["sub"]["single"] + P(c.name) + P("default")
        job_path = job_cfg["prefix"] + sub + P("foo")
        state_path = job_cfg["state"] + sub + P("foo")

        await c.d_set(
            job_path,
            dict(code=P("test.answer"), target=time.time(), data={}),
        )
        await c.i_sync()

        runner = SingleJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            st = await _wait_state(c, state_path, until=lambda s: s.get("result") == 42)
            assert st["stopped"] > 0
            tg.cancel_scope.cancel()


async def test_allrunner_per_node_state(cfg):
    "AllJobRunner stores its state in a per-node subtree."
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(
            CODE_EXEC_ROOT + P("test.echo"),
            dict(code="return 'ok'", is_async=True),
        )

        job_cfg = _job_cfg(sf)
        sub = job_cfg["sub"]["all"] + P("default")
        job_path = job_cfg["prefix"] + sub + P("e")
        state_path = job_cfg["state"] + sub + P(c.name) + P("e")

        await c.d_set(
            job_path,
            dict(code=P("test.echo"), target=time.time(), data={}),
        )
        await c.i_sync()

        runner = AllJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            st = await _wait_state(c, state_path, until=lambda s: s.get("result") == "ok")
            assert st["stopped"] > 0
            tg.cancel_scope.cancel()


async def test_call_admin_watch_and_timer(cfg):
    """``CallAdmin.watch`` + ``CallAdmin.timer`` cooperate.

    The snippet subscribes to a link path, then arms a timer when it sees
    the magic value. When the timer fires it returns. This exercises
    :class:`~moat.link.job.ChangeMsg`, :class:`~moat.link.job.ReadyMsg`,
    and :class:`~moat.link.job.TimerMsg`.
    """
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(
            CODE_EXEC_ROOT + P("test.watch"),
            dict(
                code="""
import anyio
s = _self
await s.setup_done()
await s.watch(_P("test.trigger"))
async for msg in _info:
    if isinstance(msg, _cls.TimerMsg):
        return 99
    if isinstance(msg, _cls.ChangeMsg) and msg.value == 42:
        await s.timer(0.5)
""",
                is_async=True,
            ),
        )

        # Pre-set so the initial watch fetch sees a value (we'll change it).
        await c.d_set(P("test.trigger"), 0)

        job_cfg = _job_cfg(sf)
        sub = job_cfg["sub"]["group"] + P("default")
        job_path = job_cfg["prefix"] + sub + P("w")
        state_path = job_cfg["state"] + sub + P("w")

        await c.d_set(
            job_path,
            dict(code=P("test.watch"), target=time.time(), data={}),
        )
        await c.i_sync()

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            # Wait for the job to start, then trigger it.
            await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("started", 0) > 0,
            )
            await anyio.sleep(0.5)  # let watch get its initial value
            await c.d_set(P("test.trigger"), 42)
            await c.i_sync()
            st = await _wait_state(c, state_path, until=lambda s: s.get("result") == 99)
            assert st["stopped"] > 0
            tg.cancel_scope.cancel()


async def test_call_admin_monitor_mqtt(cfg):
    "``CallAdmin.monitor`` delivers MQTT messages as MQTTmsg events."
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(
            CODE_EXEC_ROOT + P("test.mqtt"),
            dict(
                code="""
s = _self
await s.setup_done()
await s.monitor(_P("test.bus"))
async for msg in _info:
    if isinstance(msg, _cls.MQTTmsg) and msg.value == 7:
        return 'mqtt-ok'
""",
                is_async=True,
            ),
        )

        job_cfg = _job_cfg(sf)
        sub = job_cfg["sub"]["group"] + P("default")
        job_path = job_cfg["prefix"] + sub + P("m")
        state_path = job_cfg["state"] + sub + P("m")

        await c.d_set(
            job_path,
            dict(code=P("test.mqtt"), target=time.time(), data={}),
        )
        await c.i_sync()

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("started", 0) > 0,
            )
            await anyio.sleep(0.5)
            # Publish on the topic the snippet is listening on.
            await c.send(P("test.bus"), 7, retain=False)
            st = await _wait_state(c, state_path, until=lambda s: s.get("result") == "mqtt-ok")
            assert st["stopped"] > 0
            tg.cancel_scope.cancel()


async def test_call_admin_error_records_backoff(cfg):
    """A snippet that raises is reported and back-off increments."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(
            CODE_EXEC_ROOT + P("test.boom"),
            dict(code="raise RuntimeError('boom')", is_async=True),
        )

        job_cfg = _job_cfg(sf)
        sub = job_cfg["sub"]["group"] + P("default")
        job_path = job_cfg["prefix"] + sub + P("b")
        state_path = job_cfg["state"] + sub + P("b")

        await c.d_set(
            job_path,
            dict(code=P("test.boom"), target=time.time(), data={}),
        )
        await c.i_sync()

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            st = await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("backoff", 0) > 0,
            )
            assert st["stopped"] > 0
            assert st.get("result", None) is None
            tg.cancel_scope.cancel()


async def test_no_code_no_run(cfg):
    "A job record without a ``code`` field is ignored."
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        job_cfg = _job_cfg(sf)
        sub = job_cfg["sub"]["group"] + P("default")
        job_path = job_cfg["prefix"] + sub + P("idle")
        state_path = job_cfg["state"] + sub + P("idle")

        await c.d_set(job_path, dict(target=time.time(), data={}))
        await c.i_sync()

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            await anyio.sleep(3)
            # If a state record exists, the job was never actually
            # started (just an informational "no code" marker).
            try:
                st = await c.d_get(state_path)
            except KeyError:
                st = None
            if st is not None:
                assert st.get("started", 0) == 0
                assert st.get("reason") == "no code"
            tg.cancel_scope.cancel()


async def _setup_long_job(
    sf: Scaffold,
    c: Any,
    name: str,
) -> tuple[attrdict, P, P, P]:
    """Define a long-running snippet + job and return the relevant paths.

    The snippet calls ``setup_done`` (clearing back-off) and then sleeps
    until cancelled, so we can observe state transitions from outside.
    """
    await c.d_set(
        CODE_EXEC_ROOT + P("test.sleeper"),
        dict(
            code="""
import anyio
await _self.setup_done()
await anyio.sleep_forever()
""",
            is_async=True,
        ),
    )
    job_cfg = _job_cfg(sf)
    sub = job_cfg["sub"]["group"] + P("default")
    job_path = job_cfg["prefix"] + sub + P(name)
    state_path = job_cfg["state"] + sub + P(name)

    await c.d_set(
        job_path,
        dict(
            code=P("test.sleeper"),
            target=time.time(),
            data={},
            delay=300,
            backoff=1.1,
        ),
    )
    await c.i_sync()
    return job_cfg, sub, job_path, state_path


async def test_cancel_when_state_deleted(cfg):
    """Deleting the ``run.job.*`` state record cancels the running job."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        job_cfg, sub, _job_path, state_path = await _setup_long_job(sf, c, "d")

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("node") == c.name and not s.get("stopped"),
            )

            # Yank the state record out from under the runner.
            #
            # Note: ``c.d.delete`` is a no-op for paths starting with
            # ``run`` (the server explicitly skips them in
            # ``maybe_update``).  The retained MQTT message is what
            # the runner watches, so clear it by publishing a NotGiven
            # payload directly with ``retain=True``.
            await c.send(Root.get() + state_path, NotGiven, retain=True)
            await c.i_sync()

            # The runner must observe the deletion and cancel; afterwards
            # ``stopped`` is set again.
            st = await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("stopped", 0) > 0,
            )
            # ``started`` may have been wiped by the deletion notification;
            # what matters is that the runner observed it and saved a
            # ``stopped`` record (i.e. it cancelled).
            assert st["stopped"] > 0
            tg.cancel_scope.cancel()


async def test_cancel_when_state_node_cleared(cfg):
    """Clearing ``state.node`` cancels the running job."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        job_cfg, sub, _job_path, state_path = await _setup_long_job(sf, c, "n")

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            st = await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("node") == c.name and not s.get("stopped"),
            )

            tampered = dict(st)
            tampered["node"] = None
            await c.d_set(state_path, tampered, retain=True)
            await c.i_sync()

            st = await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("stopped", 0) > 0,
            )
            assert st["started"] > 0
            tg.cancel_scope.cancel()


async def test_cancel_when_state_node_reassigned(cfg):
    """Reassigning ``state.node`` to another node cancels the running job."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        job_cfg, sub, _job_path, state_path = await _setup_long_job(sf, c, "r")

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            st = await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("node") == c.name and not s.get("stopped"),
            )

            tampered = dict(st)
            tampered["node"] = "someone_else"
            await c.d_set(state_path, tampered, retain=True)
            await c.i_sync()

            # We stop, but ``node`` keeps the externally-set value: the
            # other node is supposedly running it now, so it's not ours
            # to clear.
            st = await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("stopped", 0) > 0,
            )
            assert st["started"] > 0
            assert st["node"] == "someone_else"
            tg.cancel_scope.cancel()


async def test_failing_job_records_error(cfg):
    """A snippet that throws on every run is recorded at ``error/<job>``."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await c.d_set(
            CODE_EXEC_ROOT + P("test.boom"),
            dict(code="raise RuntimeError('boom')", is_async=True),
        )

        job_cfg = _job_cfg(sf)
        sub = job_cfg["sub"]["group"] + P("default")
        job_path = job_cfg["prefix"] + sub + P("err")
        state_path = job_cfg["state"] + sub + P("err")
        error_path = P("error") + job_path

        await c.d_set(
            job_path,
            dict(code=P("test.boom"), target=time.time(), data={}, delay=2),
        )
        await c.i_sync()

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            # Wait until the runner has noticed the failure (backoff > 0).
            await _wait_state(c, state_path, until=lambda s: s.get("backoff", 0) > 0)

            # The runner reports the exception through the link's error
            # channel, which stores a record at error/<job_path>.
            with anyio.fail_after(5):
                while True:
                    try:
                        err = await c.d_get(error_path)
                    except KeyError:
                        await anyio.sleep(0.1)
                        continue
                    if isinstance(err, dict) and "exc" in err:
                        break
                    await anyio.sleep(0.1)
            assert "exc" in err
            tg.cancel_scope.cancel()


async def test_recovering_job_clears_error(cfg):
    """A job that failed before but now runs cleanly clears its error.

    The job's code path is rewritten from a failing snippet to a
    successful one mid-run; the runner picks up the new code on its
    next retry, runs it to completion, and its
    :py:meth:`~moat.link.client.LinkSender.e_ok` call removes the
    error record.
    """
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        # Initial snippet always raises.
        await c.d_set(
            CODE_EXEC_ROOT + P("test.flip"),
            dict(code="raise RuntimeError('boom')", is_async=True),
        )

        job_cfg = _job_cfg(sf)
        sub = job_cfg["sub"]["group"] + P("default")
        job_path = job_cfg["prefix"] + sub + P("flip")
        state_path = job_cfg["state"] + sub + P("flip")
        error_path = P("error") + job_path

        # Short delay so the retry happens quickly.
        await c.d_set(
            job_path,
            dict(code=P("test.flip"), target=time.time(), data={}, delay=1),
        )
        await c.i_sync()

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            # First, observe the failure and the recorded error.
            await _wait_state(c, state_path, until=lambda s: s.get("backoff", 0) > 0)
            with anyio.fail_after(5):
                while True:
                    try:
                        await c.d_get(error_path)
                        break
                    except KeyError:
                        await anyio.sleep(0.1)

            # Now swap the snippet for one that returns cleanly.
            await c.d_set(
                CODE_EXEC_ROOT + P("test.flip"),
                dict(code="return 'ok'", is_async=True),
            )
            await c.i_sync()

            # The runner's next retry runs the new code; on clean
            # completion it calls ``e_ok`` which removes the error
            # record.
            with anyio.fail_after(20):
                while True:
                    try:
                        await c.d_get(error_path)
                    except KeyError:
                        break
                    await anyio.sleep(0.1)

            # And the backoff counter should drop back to zero.
            st = await _wait_state(c, state_path, until=lambda s: s.get("backoff", 0) == 0)
            assert st.get("result") == "ok"
            tg.cancel_scope.cancel()


async def test_restart_when_code_changes(cfg):
    """Changing a running job's code snippet cancels and restarts it.

    The job initially runs a snippet that sleeps forever (after
    signalling setup).  Rewriting the code at
    ``code.exec.test.sleeper`` to a snippet that returns immediately
    must cause the runner to notice the change, cancel the long-running
    task, and re-run the job with the new code.
    """
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        job_cfg, sub, _job_path, state_path = await _setup_long_job(sf, c, "rc")

        runner = AnyJobRunner(c, job_cfg, sub, nodes=1)
        async with anyio.create_task_group() as tg, runner.run():
            # Wait until the long-running job is actually running here.
            await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("node") == c.name and not s.get("stopped"),
            )

            # Replace the snippet with one that returns immediately.
            await c.d_set(
                CODE_EXEC_ROOT + P("test.sleeper"),
                dict(code="return 'restarted'", is_async=True),
            )
            await c.i_sync()

            # The runner notices the change, cancels the old task, and
            # restarts the job with the new code, which completes.
            st = await _wait_state(
                c,
                state_path,
                until=lambda s: s.get("result") == "restarted",
            )
            assert st["stopped"] > 0
            tg.cancel_scope.cancel()
