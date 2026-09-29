"""
Running the test cases of code snippets.

A test runs its snippet exactly as ``moat link job`` would (via
`moat.link.job.runner.run_job`), below a fresh test root (see
`moat.link.code.testroot`), and executes the test's actions against it.

See ``TODO/codetest.md``, sections "Actions" and "Running the code".
"""

from __future__ import annotations

import anyio
import logging
import time
from contextlib import suppress

import simpleeval
from attrs import define, field

from moat.util import NotGiven, ungroup
from moat.lib.path import P, Path
from moat.lib.run import process_args
from moat.link.code.steps import format_step
from moat.link.code.testroot import with_test_root
from moat.link.job.runner import run_job

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.link.client import LinkSender
    from moat.link.code.case import CodeTest
    from moat.link.code.testroot import TestRoot

    from collections.abc import Iterable

__all__ = ["TestFailed", "TestOutcome", "run_test", "run_tests"]

logger = logging.getLogger(__name__)

EXPR_FUNCTIONS = dict(P=P, len=len, abs=abs, min=min, max=max, round=round, str=str)
"Functions available in expressions."

DEFAULT_CODEC = "std-cbor"
"Codec for raw MQTT messages, unless the step names one."

JOB_PATH = Path.build((None, "job"))
"Below the test root: the (virtual) job's path, used for its errors."

STATE_PATH = Path.build((None, "state"))
"Below the test root: the job's state."


class TestFailed(Exception):
    """
    A test step failed.

    ``step`` is the step's 1-based index, if the failure is due to one.
    """

    __test__ = False  # not a pytest class

    def __init__(self, msg: str, step: int | None = None):
        super().__init__(msg)
        self.msg = msg
        self.step = step

    def __str__(self):
        if self.step is None:
            return self.msg
        return f"step {self.step}: {self.msg}"


@define
class TestOutcome:
    """
    The outcome of one test run.
    """

    __test__ = False  # not a pytest class

    ok: bool = False
    "Did the test pass?"

    message: str | None = None
    "Why it failed."

    step: int | None = None
    "The step (1-based) that failed, if any."

    root: Path | None = None
    "The test root."

    result: Any = NotGiven
    "The snippet's return value, if it ended."

    error: BaseException | None = None
    "The snippet's exception, if it raised."

    duration: float = 0
    "Seconds."

    log: list[str] = field(factory=list)
    "What happened, one line per step."

    def __str__(self):
        if self.ok:
            return "OK"
        return f"FAIL: step {self.step}: {self.message}" if self.step else f"FAIL: {self.message}"


class _Run:
    """
    One run of a test case.
    """

    job_done: anyio.Event
    job_scope: anyio.CancelScope | None = None
    job_started: bool = False
    error_expected: bool = False

    def __init__(
        self,
        link: LinkSender,
        code: Path,
        test: CodeTest,
        root: TestRoot,
        out: TestOutcome,
        log_stream: Any = None,
    ):
        self.link = link
        self.code = code
        self.test = test
        self.root = root
        self.out = out
        self.log_stream = log_stream
        self.job_done = anyio.Event()
        self._changed = anyio.Event()
        self.names: dict[str, Any] = {"result": None, "error": None}
        self.eval = simpleeval.EvalWithCompoundTypes(
            names=self.names,
            functions=EXPR_FUNCTIONS,
        )

    def log(self, msg: str) -> None:
        "Record a line in the test's log."
        self.out.log.append(msg)
        logger.debug("%s: %s", self.root.path, msg)

    def changed(self) -> None:
        "Something an expression might look at has changed."
        self._changed.set()
        self._changed = anyio.Event()

    def check(self, expr: str) -> Any:
        "Evaluate an expression."
        try:
            return self.eval.eval(expr)
        except Exception as exc:
            raise TestFailed(f"{expr}: {exc!r}") from exc

    # Setup

    async def load_data(self, path: Path, data: Any) -> None:
        """
        Store the test's initial data, in ``get -rd_`` format: a mapping's
        ``_`` entry is the value at its node, other keys are children.
        Non-mappings are stored directly.
        """
        if not isinstance(data, Mapping):
            await self.link.d_set(path, self.root.resolve(data))
            return
        for k, v in data.items():
            if k == "_":
                await self.link.d_set(path, self.root.resolve(v))
            else:
                await self.load_data(path / k, v)

    # The job

    async def _job(self, *, task_status=anyio.TASK_STATUS_IGNORED) -> None:
        job = dict(code=self.code, data=self.root.resolve(self.test.args))
        try:
            with anyio.CancelScope() as sc:
                self.job_scope = sc
                task_status.started()
                try:
                    self.out.result = await run_job(
                        self.link,
                        job,
                        self.root.path + JOB_PATH,
                        self.root.path + STATE_PATH,
                        log_stream=self.log_stream,
                        report=False,
                    )
                except Exception as exc:
                    self.out.error = ungroup.one(exc)
                    self.names["error"] = self.out.error
                    self.log(f"snippet raised {self.out.error!r}")
                else:
                    self.names["result"] = self.out.result
                    self.log(f"snippet returned {self.out.result!r}")
        finally:
            self.job_scope = None
            self.job_done.set()
            self.changed()

    async def start(self, tg) -> None:
        "Start the snippet."
        if self.job_started:
            raise TestFailed("the snippet has already been started")
        self.job_started = True
        await tg.start(self._job)

    async def stop(self) -> None:
        "Cancel the snippet, if it is still running, and wait for it to end."
        if self.job_scope is not None:
            self.job_scope.cancel()
        if self.job_started:
            await self.job_done.wait()

    # Monitors

    async def _monitor_data(self, name: str, path: Path, *, task_status) -> None:
        values: list = []
        self.names[name] = values
        async with self.link.d_watch(path, state=None, mark=True, meta=False) as mon:
            marked = False
            async for item in mon:
                if not marked and item is None:
                    marked = True
                    task_status.started()
                    continue
                values.append(None if item is NotGiven else item)
                self.changed()

    async def _monitor_mqtt(self, name: str, path: Path, codec: str, *, task_status) -> None:
        values: list = []
        self.names[name] = values
        async with self.link.monitor(path, codec=codec, retained=False) as mon:
            task_status.started()
            async for msg in mon:
                values.append(msg.data)
                self.changed()

    # Actions

    async def wait(self, timeout: float, expr: str | None = None) -> None:
        "Wait for @timeout seconds, or until @expr is true."
        if expr is None:
            await anyio.sleep(timeout)
            return
        with anyio.move_on_after(timeout):
            while not self.check(expr):
                await self._changed.wait()
            return
        msg = f"timeout waiting for {expr}"
        if self.out.error is not None:
            msg += f"; the snippet raised {self.out.error!r}"
        raise TestFailed(msg)

    async def step(self, tg, step: list) -> None:
        "Execute one action."
        verb, *args = step
        r = self.root.resolve
        match verb:
            case "comment":
                pass
            case "start":
                await self.start(tg)
            case "set":
                await self.link.d_set(r(args[0]), r(args[1]))
                await self.link.i_sync()
            case "update":
                path = r(args[0])
                try:
                    val = await self.link.d_get(path)
                except KeyError:
                    val = None
                val = process_args(
                    val if val is not None else {},
                    vars_=list(zip(args[1::2], r(args[2::2]), strict=True)),
                )
                await self.link.d_set(path, val)
                await self.link.i_sync()
            case "delete":
                with suppress(KeyError):
                    await self.link.d.delete(r(args[0]))
                await self.link.i_sync()
            case "send":
                codec = args[2] if len(args) > 2 else DEFAULT_CODEC
                await self.link.send(r(args[0]), r(args[1]), codec=codec, retain=False)
            case "monitor":
                name, path, *mqtt = args
                if mqtt:
                    codec = mqtt[1] if len(mqtt) > 1 else DEFAULT_CODEC
                    await tg.start(self._monitor_mqtt, name, r(path), codec)
                else:
                    await tg.start(self._monitor_data, name, r(path))
            case "wait":
                await self.wait(*args)
            case "sleep":
                await anyio.sleep(args[0])
            case "check":
                if not self.check(args[0]):
                    raise TestFailed(f"false: {args[0]}")
            case "result":
                await self.job_done.wait()
                if self.out.error is not None:
                    raise TestFailed(f"the snippet raised {self.out.error!r}")
                if args and not self.check(args[0]):
                    raise TestFailed(f"false: {args[0]} (result={self.out.result!r})")
            case "error":
                self.error_expected = True
                await self.job_done.wait()
                if self.out.error is None:
                    raise TestFailed(f"the snippet returned {self.out.result!r}")
                if args and not self.check(args[0]):
                    raise TestFailed(f"false: {args[0]} (error={self.out.error!r})")
            case _:
                raise TestFailed(f"unknown action {verb!r}")

    async def run(self) -> None:
        "Run the test's steps."
        test = self.test
        await self.load_data(self.root.path, test.data)
        await self.link.i_sync()

        async with anyio.create_task_group() as tg:
            try:
                for n, step in enumerate(test.steps, start=1):
                    if not self.job_started and step[0] not in ("monitor", "comment", "start"):
                        self.log("start (implicit)")
                        await self.start(tg)
                    self.log(format_step(step).rstrip())
                    try:
                        await self.step(tg, step)
                    except TestFailed as exc:
                        if exc.step is None:
                            exc.step = n
                        raise
                if not self.job_started:
                    self.log("start (implicit)")
                    await self.start(tg)
                if self.out.error is not None and not self.error_expected:
                    raise TestFailed(f"the snippet raised {self.out.error!r}")
            finally:
                with anyio.CancelScope(shield=True):
                    await self.stop()
                tg.cancel_scope.cancel()


async def run_test(
    link: LinkSender,
    code: Path,
    test: CodeTest,
    *,
    keep: bool = False,
    log_stream: Any = None,
) -> TestOutcome:
    """
    Run one test case of the snippet at ``code``.

    Args:
        link: Connected MoaT-Link client.
        code: The snippet's path, below the code root.
        test: The test case.
        keep: Don't delete the test root afterwards.
        log_stream: Mirror the snippet's ``_log`` output to this stream.

    Returns:
        The test's outcome. Failures are reported there, not raised.
    """
    out = TestOutcome()
    t = time.monotonic()
    try:
        async with with_test_root(link, keep=keep) as root:
            out.root = root.path
            run = _Run(link, code, test, root, out, log_stream=log_stream)
            try:
                with anyio.fail_after(test.timeout):
                    await run.run()
            except TimeoutError:
                raise TestFailed(f"timeout after {test.timeout} seconds") from None
    except TestFailed as exc:
        out.message = exc.msg
        out.step = exc.step
    except Exception as exc:
        err = ungroup.one(exc)
        if isinstance(err, TestFailed):
            out.message = err.msg
            out.step = err.step
        else:
            logger.debug("Test error", exc_info=err)
            out.message = f"test error: {err!r}"
    else:
        out.ok = True
    out.duration = time.monotonic() - t
    if out.message is not None:
        out.log.append(f"FAIL: {out.message}")
    return out


async def run_tests(
    link: LinkSender,
    tests: Iterable[tuple[Any, Path, CodeTest]],
    *,
    limit: int | None = None,
    keep: bool = False,
    log_stream: Any = None,
) -> list[tuple[Any, TestOutcome]]:
    """
    Run several tests in parallel.

    Args:
        tests: ``(key, code, test)`` tuples. The key identifies the test
               in the result and is otherwise ignored.
        limit: Run at most this many tests at the same time.

    Returns:
        ``(key, outcome)`` tuples, in the order of @tests.
    """
    tests = list(tests)
    res: list[Any] = [None] * len(tests)
    lim = anyio.CapacityLimiter(limit) if limit else None

    async def _one(i: int, key: Any, code: Path, test: CodeTest) -> None:
        if lim is None:
            out = await run_test(link, code, test, keep=keep, log_stream=log_stream)
        else:
            async with lim:
                out = await run_test(link, code, test, keep=keep, log_stream=log_stream)
        res[i] = (key, out)

    async with anyio.create_task_group() as tg:
        for i, (key, code, test) in enumerate(tests):
            tg.start_soon(_one, i, key, code, test)
    return res
