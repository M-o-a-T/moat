"""
Fixtures for the heat controller tests (HEAT.md §5.4).

- ``heat_scaffold``, ``link``: a MoaT-Link test server and a client.
- ``heat``: a :class:`HeatScaffold` for running units against that server.
- ``trace_check``: compare a trace with its stored reference; rewrite the
  reference only with ``--heat-refresh``.

The closed-loop runner itself is :class:`moat.dev.heat.sim.loop.ClosedLoop`.
"""

from __future__ import annotations

import anyio
import pytest
from pathlib import Path as FSPath

from moat.dev.heat.config import CFG_PATH, ServiceCfg, load_config
from moat.dev.heat.link import PWM_UNIT, Reader, ServiceMonitor, out_path
from moat.dev.heat.sim.trace import compare, dump, load
from moat.dev.heat.state import state_path
from moat.lib.path import P
from moat.link._test import Scaffold

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import TaskGroup, TaskStatus

    from moat.dev.heat.unit import Unit
    from moat.lib.path import Path
    from moat.link.client import LinkSender

    from collections.abc import AsyncIterator, Callable, Mapping

DATA = FSPath(__file__).parent / "data"
TMO = 2


@pytest.fixture(autouse=True)
def _heat_cfg(cfg) -> None:
    "the static config (with the package defaults), also for tests without a server"


@pytest.fixture
async def heat_scaffold(cfg) -> AsyncIterator[Scaffold]:
    "a MoaT-Link test server"
    async with Scaffold(cfg, use_servers=True) as sf, sf.server_(init={}):
        yield sf


@pytest.fixture
async def link(heat_scaffold: Scaffold) -> AsyncIterator[LinkSender]:
    "a client of the test server"
    async with heat_scaffold.client_() as c:
        yield c


class UnitHandle:
    """A unit running against the test server, with its client and published data."""

    def __init__(
        self,
        unit: Unit[Any, Any],
        scope: anyio.CancelScope,
        out: Reader[Any],
        state: Reader[Any],
        service: ServiceMonitor,
    ) -> None:
        self.unit = unit
        self.link = unit.link
        self._scope = scope
        self._out = out
        self._state = state
        self._service = service

    @property
    def out(self) -> Any:
        """The unit's published view (``app.heat.<unit>.out``)."""
        return self._out.value

    @property
    def state(self) -> Any:
        """The unit's saved state (``app.heat.<unit>.state``), as stored."""
        return self._state.value

    @property
    def alive(self) -> bool:
        """Whether the unit's service announcement is up."""
        return self._service.alive

    def cancel(self) -> None:
        """
        Stop the unit by cancelling it. Its service announcement is withdrawn.
        """
        self._scope.cancel()

    async def wait(self, what: str, pred: Callable[[Any], bool], timeout: float = TMO) -> Any:
        """Wait until ``pred`` holds for ``out``, ``state`` or ``alive``."""
        r = {"out": self._out, "state": self._state, "alive": self._service}[what]
        with anyio.fail_after(timeout):
            while not pred(self.alive if what == "alive" else r.value):
                await r.wait_changed()
        return self.alive if what == "alive" else r.value


class HeatScaffold:
    """
    Runs heat units against a MoaT-Link test server (real time, short timeouts).

    Args:
        sf: The test server scaffold.
        link: A client, for seeding, feeding and watching.
        tg: A task group that outlives the test's units.
    """

    def __init__(self, sf: Scaffold, link: LinkSender, tg: TaskGroup) -> None:
        self.sf = sf
        self.link = link
        self.tg = tg

    async def seed_config(self, unit: str, data: Mapping[str, Any]) -> None:
        """Store a unit's config item (``cfg.app.heat.<unit>``)."""
        await self.link.d_set(CFG_PATH / unit, dict(data), retain=True, verify=False)

    async def feed(self, path: Path, value: Any) -> None:
        """Publish a retained value, as a sensor or another unit would."""
        await self.link.d_set(path, value, retain=True)

    async def expect(self, path: Path, pred: Callable[[Any], bool], timeout: float = TMO) -> Any:
        """Wait until ``pred(value)`` holds for the item at ``path``; return the value."""
        r = Reader[Any](self.link, path)
        sc = anyio.CancelScope()
        await self.tg.start(self._watch, r, sc)
        try:
            with anyio.fail_after(timeout):
                while not pred(r.value):
                    await r.wait_changed()
            return r.value
        finally:
            sc.cancel()

    @staticmethod
    async def _watch(
        r: Reader[Any], sc: anyio.CancelScope, *, task_status: TaskStatus[None]
    ) -> None:
        with sc:
            await r.run(task_status=task_status)

    async def run_pwm(self) -> anyio.CancelScope:
        """
        Announce the PWM daemon's service, which the pump unit requires.

        Cancel the scope to withdraw it.
        """
        return await self.tg.start(self._pwm)

    async def _pwm(self, *, task_status: TaskStatus[anyio.CancelScope]) -> None:
        svc = await load_config(self.link, "service", ServiceCfg)
        async with self.sf.client_() as c:
            with anyio.CancelScope() as sc:
                async with c.announcing(P("heat") / PWM_UNIT, host=svc.host) as srv:
                    srv.set()
                    await c.i_sync()
                    task_status.started(sc)
                    await anyio.sleep_forever()

    async def run_unit(self, unit: type[Unit[Any, Any]], save_delay: float = 0.1) -> UnitHandle:
        """Start a unit on its own client; returns once it is running."""
        svc = await load_config(self.link, "service", ServiceCfg)
        out = Reader[Any](self.link, out_path(unit.name))
        state = Reader[Any](self.link, state_path(unit.name))
        service = ServiceMonitor(self.link, svc.host, unit.name)
        for r in (out, state, service):
            await self.tg.start(r.run)
        u, sc = await self.tg.start(self._run, unit, save_delay)
        return UnitHandle(u, sc, out, state, service)

    async def _run(
        self,
        unit: type[Unit[Any, Any]],
        save_delay: float,
        *,
        task_status: TaskStatus[tuple[Unit[Any, Any], anyio.CancelScope]],
    ) -> None:
        with anyio.CancelScope() as sc:
            async with self.sf.client_() as c:
                u = unit(c, save_delay=save_delay)
                async with anyio.create_task_group() as tg:
                    await tg.start(u.run)
                    task_status.started((u, sc))


@pytest.fixture
async def heat(heat_scaffold: Scaffold, link: LinkSender) -> AsyncIterator[HeatScaffold]:
    "run heat units against the test server"
    async with anyio.create_task_group() as tg:
        yield HeatScaffold(heat_scaffold, link, tg)
        tg.cancel_scope.cancel()


@pytest.fixture
def trace_check(request, tmp_path_factory) -> Callable[..., None]:
    """
    Compare a trace with its stored reference.

    ``trace_check(trace, ref_file, tol=0.002)``: ``trace`` is a dict as
    taken by :func:`~moat.dev.heat.sim.trace.dump`. With ``--heat-refresh``
    the reference is (re)written and the test is skipped; a missing
    reference fails. Differences are written to a temporary file, along
    with the new trace.
    """
    refresh = request.config.getoption("--heat-refresh")

    def check(
        trace: Mapping[str, Any], ref_file: FSPath, tol: float | Mapping[str, float] = 0.002
    ) -> None:
        text = dump(trace)
        if refresh:
            ref_file.parent.mkdir(parents=True, exist_ok=True)
            ref_file.write_text(text)
            pytest.skip(f"{ref_file.name} written")
        if not ref_file.exists():
            pytest.fail(f"No reference trace {ref_file}; create it with --heat-refresh")
        diffs = compare(load(ref_file.read_text()), load(text), tol)
        if diffs:
            d = tmp_path_factory.mktemp("heat-trace")
            (d / f"{ref_file.stem}.json").write_text(text)
            (d / f"{ref_file.stem}.diff").write_text("\n".join(diffs) + "\n")
            pytest.fail(
                f"{ref_file.name}: {len(diffs)} difference(s), see {d}/{ref_file.stem}.diff\n"
                + "\n".join(diffs[:5])
            )

    return check


@pytest.fixture
def jump(autojump_clock: Any) -> Any:
    """
    For end-to-end tests: trio's mock clock, jumping as soon as the test
    has been idle for 5 ms (50 ms is four times slower).

    It must be returned: pytest-trio only uses a clock that is the value
    of one of the test's fixtures.
    """
    autojump_clock.autojump_threshold = 0.005
    return autojump_clock
