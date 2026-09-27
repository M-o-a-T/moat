"""
Run the legacy ``solvis.Data`` controller against the plant simulator.

This is the characterisation harness for moat-n84.7: it produces the
reference traces the new units are compared against (HEAT.md §5.1).

Isolation: ``solvis`` is imported with a dummy ``/etc/moat/moat.cfg`` and
its ``open_client`` is replaced by a function that raises, so nothing
here can reach a MoaT-KV server or an MQTT broker. All KV traffic goes
through :class:`FakeKV`, an in-memory stand-in.

Time: the event loop runs on trio's ``MockClock``, stepped by hand; the
simulator is advanced in lock-step with it, ``Data.TS`` and
``moat.util.time`` report simulated wall-clock time, and
``datetime.datetime.now`` (used by the heating-curve schedule) is patched
to the same clock in a fixed time zone.

Delete together with ``solvis.py`` (HEAT.md §4.2).
"""

from __future__ import annotations

import anyio
import builtins
import contextlib
import datetime as _dt
import importlib
import io
import json
import logging
import sys
import time as _time
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path as FSPath
from unittest import mock

from moat.util import attrdict, combine_dict, yload
from moat.util import time as mtime
from moat.dev.heat.sim import Plant, PlantCfg
from moat.lib.path import P, Path
from moat.lib.pid import _impl as _pid_impl

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Callable

DATA = FSPath(__file__).parent / "data"
TRACES = DATA / "legacy"

TZ = _dt.timezone(_dt.timedelta(hours=1), "CET")
EPOCH = _dt.datetime(2026, 1, 5, tzinfo=TZ).timestamp()  # a Monday, local midnight

__all__ = ["SCENARIOS", "FakeKV", "Scenario", "load_solvis", "run_scenario"]


def load_solvis() -> Any:
    """Import the legacy module without its host config and without a KV client."""
    mod = sys.modules.get("moat.dev.heat.solvis")
    if mod is None:
        real_open = builtins.open

        def fake_open(f: Any, *a: Any, **k: Any) -> Any:
            if str(f) == "/etc/moat/moat.cfg":
                return io.StringIO("kv: {}\n")
            return real_open(f, *a, **k)

        # solvis also calls logging.basicConfig at import time; the test
        # suite forbids that, and the harness doesn't want it either
        with (
            mock.patch("builtins.open", fake_open),
            mock.patch("logging.basicConfig", return_value=None),
        ):
            mod = importlib.import_module("moat.dev.heat.solvis")

    def no_client(*_a: Any, **_k: Any) -> Any:
        raise RuntimeError("The legacy harness must not connect to MoaT-KV")

    setattr(mod, "open_client", no_client)  # noqa: B010
    return mod


def legacy_cfg() -> attrdict:
    """The legacy defaults, overlaid with the production config (data/solvis.yml)."""
    solvis = load_solvis()
    cfg = yload(solvis.CFG, attr=True)
    over = yload((DATA / "solvis.yml").read_text(), attr=True)
    return combine_dict(over, cfg, cls=attrdict)


class FakeKV:
    """
    Just enough of the MoaT-KV client API for ``solvis.Data``.

    ``set`` records the write, updates the value, notifies watchers and
    calls :attr:`on_set`; :meth:`publish` does the same for values that
    come from the plant.
    """

    def __init__(self) -> None:
        self.values: dict[Path, Any] = {}
        self._watch: list[tuple[Path, bool, bool, Any]] = []  # path, exact, long, stream
        self.on_set: Callable[[Path, Any], None] | None = None
        self.writes: list[tuple[Path, Any]] = []

    async def get(self, path: Path) -> attrdict:  # noqa: D102
        if path in self.values:
            return attrdict(path=path, value=self.values[path])
        return attrdict(path=path)

    @asynccontextmanager
    async def watch(
        self,
        path: Path,
        max_depth: int | None = None,
        fetch: bool = False,
        long_path: bool = True,
        **_kw: Any,
    ) -> AsyncIterator[Any]:
        """Watch a path (``max_depth=0``) or a subtree; ``fetch`` sends current values first."""
        send, recv = anyio.create_memory_object_stream[attrdict](1000)
        exact = max_depth == 0
        if fetch:
            for p, v in list(self.values.items()):
                if p == path if exact else p[: len(path)] == path:
                    send.send_nowait(self._msg(path, p, v, long_path))
            send.send_nowait(attrdict(state="uptodate"))
        w = (path, exact, long_path, send)
        self._watch.append(w)
        try:
            async with recv:
                yield recv
        finally:
            self._watch.remove(w)
            send.close()

    @staticmethod
    def _msg(base: Path, p: Path, v: Any, long_path: bool) -> attrdict:
        return attrdict(path=p if long_path else p[len(base) :], value=v)

    def _notify(self, p: Path, v: Any) -> None:
        for base, exact, long_path, send in self._watch:
            if p == base if exact else p[: len(base)] == base:
                send.send_nowait(self._msg(base, p, v, long_path))

    def publish(self, p: Path, v: Any) -> None:
        """A value from outside the controller (plant, operator)."""
        if self.values.get(p, NotImplemented) == v and p in self.values:
            return
        self.values[p] = v
        self._notify(p, v)

    async def set(self, path: Path, value: Any = None, idem: bool = False, **_kw: Any) -> None:  # noqa: D102
        if idem and path in self.values and self.values[path] == value:
            return
        self.writes.append((path, value))
        self.values[path] = value
        self._notify(path, value)
        if self.on_set is not None:
            self.on_set(path, value)


@dataclass
class Scenario:
    """A closed-loop run of the legacy controller."""

    name: str
    doc: str
    duration: float
    plant: dict[str, Any] = field(default_factory=dict)  # PlantCfg overrides
    cmd: dict[str, Any] = field(default_factory=dict)  # initial operator inputs
    events: list[tuple[float, str, Any]] = field(default_factory=list)
    start: float = 0  # seconds after local midnight
    seed: int = 1
    dt: float = 10
    sample: float = 60


# operator / Solvis inputs, keyed by name → legacy config path
_CMD = {
    "c_flow": "cmd.flow",
    "c_bypass": "cmd.bypass.cmd",
    "c_bypass_mode": "cmd.bypass.mode",
    "c_bypass_power": "cmd.bypass.power",
    "cm_wp": "cmd.wp",
    "cm_heat": "cmd.heat",
    "cm_pellet_force": "cmd.pellet.force",
    "c_heat_night": "setting.heat.night",
    "c_water": "setting.water",
    "force_day": "setting.heat.mode.force.day.cmd",
    "force_night": "setting.heat.mode.force.night.cmd",
}
_CMD_DEFAULT = {
    "c_flow": 0.0,
    "c_bypass": False,
    "c_bypass_mode": 0,
    "c_bypass_power": 0.0,
    "cm_wp": True,
    "cm_heat": True,
    "cm_pellet_force": None,
    "c_heat_night": 30,
    "c_water": 50,
}

# plant sensor → legacy config path(s)
_SENSORS = {
    "t_in": ("sensor.pump.in",),
    "t_out": ("sensor.pump.out",),
    "r_flow": ("sensor.pump.flow",),
    "m_ice": ("sensor.pump.ice",),
    "m_power": ("sensor.power",),
    "tb_water": ("sensor.buffer.top",),
    "tb_heat": ("sensor.buffer.heat",),
    "tb_mid": ("sensor.buffer.mid",),
    "tb_low": ("sensor.buffer.low",),
    "t_heat": ("sensor.temp.heat",),
    "m_air": ("sensor.temp.current", "adj.curve.current"),
    "m_air_pred": ("sensor.temp.predict",),
    "m_pellet": ("sensor.temp.pellet",),
    "m_pellet_state": ("sensor.pellet.state",),
    "m_switch": ("misc.switch.state",),
}

# values recorded in the trace: name → legacy config path
_OUT = {
    "power": "cmd.power",
    "mode": "cmd.mode.path",
    "pwm": "output.flow.path",
    "heat_mode": "setting.heat.mode.path",
    "curve": "adj.curve.setting",
    "p_wanted": "cmd.pellet.wanted",
    "p_load": "cmd.pellet.load",
    "p_temp": "cmd.pellet.temp",
}
_TRACE_SENSORS = (
    "t_in",
    "t_out",
    "r_flow",
    "m_power",
    "m_ice",
    "tb_water",
    "tb_heat",
    "tb_mid",
    "tb_low",
    "t_heat",
    "m_air",
    "m_pellet",
    "m_pellet_state",
    "m_switch",
)


def _get(cfg: Any, dotted: str) -> Any:
    for k in dotted.split("."):
        cfg = cfg[k]
    return cfg


class _FakeDT(_dt.datetime):
    clock: Callable[[], float] = _time.time

    @classmethod
    def now(cls, tz: Any = None) -> Any:
        return cls.fromtimestamp(cls.clock(), tz or TZ)

    def astimezone(self, tz: Any = None) -> Any:
        # "local time" is the fixed simulation time zone, not the host's
        return super().astimezone(tz or TZ)


class _Stdout(io.StringIO):
    """Collects the controller's chatter; keeps only the tail."""

    def write(self, s: str) -> int:
        if self.tell() > 1_000_000:
            self.seek(0)
            self.truncate()
        return super().write(s)


def _r(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 3)
    return v


async def _run(sc: Scenario, trace: dict[str, Any], mclock: Any) -> None:
    from trio.testing import wait_all_tasks_blocked  # noqa: PLC0415

    solvis = load_solvis()
    cfg = legacy_cfg()
    pcfg = PlantCfg.from_dict(combine_dict(sc.plant, {"day_offset": sc.start}))
    plant = Plant(pcfg, seed=sc.seed)
    kv = FakeKV()
    t0 = EPOCH + sc.start
    clock = lambda: t0 + plant.now  # noqa: E731
    _FakeDT.clock = clock

    cmd = {**_CMD_DEFAULT, **sc.cmd}
    patch_paths = set(cfg.adj.pellet.get("startup", {}).get("patch", {}).get("path", ()))
    cpath = {k: _get(cfg, v) for k, v in _OUT.items()}
    inp = plant.inputs

    def on_set(p: Path, v: Any) -> None:
        if p == cpath["power"]:
            inp.hp_power = v
        elif p == cpath["mode"]:
            inp.hp_mode = v
        elif p == cpath["pwm"]:
            inp.pwm = v
        elif p == cpath["heat_mode"]:
            inp.heat_mode = v
        elif p == cpath["curve"]:
            # the Solvis echoes the flow setpoint as its current heating target
            inp.heat_setpoint = v
            kv.publish(cfg.setting.heat.day, v)
        elif p == cpath["p_wanted"]:
            # in production a KV rule drives the burner from the request flag
            inp.pellet_wanted = bool(v)
            kv.publish(cfg.cmd.pellet.run, bool(v))
        elif p == cpath["p_load"]:
            inp.pellet_load = v
        elif p == cpath["p_temp"]:
            inp.pellet_temp = v
        elif p in patch_paths:
            inp.pellet_patch_goal = v

    kv.on_set = on_set

    def set_cmd(name: str, v: Any) -> None:
        if name == "c_water":
            inp.water_setpoint = v
        kv.publish(_get(cfg, _CMD[name]), v)

    last_err: dict[str, int] = {}

    def publish_sensors() -> dict[str, Any]:
        s = plant.sensors()
        for k, paths in _SENSORS.items():
            for p in paths:
                kv.publish(_get(cfg, p), s[k])
        err = s["errors"]
        base = cfg.sensor.error
        for k in last_err.keys() - err.keys():
            kv.publish(base + P(k), 0)
        for k, v in err.items():
            kv.publish(base + P(k), v)
        last_err.clear()
        last_err.update(err)
        return s

    # initial values
    for k, v in cmd.items():
        if k in _CMD:
            set_cmd(k, v)
    kv.publish(cfg.setting.heat.day, inp.heat_setpoint)
    kv.publish(cfg.sensor.cop, 3.0)
    kv.publish(cfg.cmd.pellet.wanted, False)
    kv.publish(cfg.cmd.pellet.run, False)
    publish_sensors()

    d = solvis.Data(cfg, kv, state=attrdict())
    d.TS = clock()

    samples: list[dict[str, Any]] = []
    events: list[list[Any]] = []
    trace["samples"] = samples
    trace["events"] = events
    Run = solvis.Run
    last_run = None
    todo = sorted(sc.events)

    def sample() -> None:
        nonlocal last_run
        run = Run(d.state.get("run", 0)).name
        if run != last_run:
            events.append([round(plant.now), "run", run])
            last_run = run
        if round(plant.now) % sc.sample:
            return
        s = plant.truth()
        row: dict[str, Any] = {"t": round(plant.now), "run": run, "hc": d.hc_pos}
        for k, p in cpath.items():
            row[k] = _r(kv.values.get(p))
        for k in _TRACE_SENSORS:
            row[k] = _r(s[k])
        row["hp"] = str(plant.hp.stage)
        samples.append(row)

    async with anyio.create_task_group() as tg:
        await tg.start(d.run_init)
        await tg.start(d.err_mon)
        await tg.start(d.run_temp_thresh)
        await tg.start(d.run_set_heat)
        await tg.start(d.run_set_pellet)
        await tg.start(d.run_pump)
        sample()
        while plant.now < sc.duration:
            while todo and todo[0][0] <= plant.now:
                _, what, val = todo.pop(0)
                events.append([round(plant.now), what, val])
                if what == "error":
                    path, code = val
                    if code:
                        plant.inject_error(path, code)
                    else:
                        plant.clear_error(path)
                elif what == "dhw":
                    plant.add_dhw(plant.now, *val)
                else:
                    set_cmd(what, val)
            plant.step(sc.dt)
            d.TS = clock()
            # Advance the loop clock by hand, not by sleeping: the driver has
            # no deadline of its own, so it can't tie with a controller timer
            # (trio breaks deadline ties by object address).
            mclock.jump(sc.dt)
            await wait_all_tasks_blocked()
            publish_sensors()
            await wait_all_tasks_blocked()
            sample()
        tg.cancel_scope.cancel()


def _event_set(self: Any) -> None:
    """``trio.Event.set``, waking waiters in name order instead of set (address) order."""
    from trio import lowlevel  # noqa: PLC0415

    if not self._flag:
        self._flag = True
        for task in sorted(self._tasks, key=lambda t: t.name):
            lowlevel.reschedule(task)
        self._tasks.clear()


def _now() -> float:
    # late-bound: each run installs its own clock
    return _FakeDT.clock()


def run_scenario(sc: Scenario) -> dict[str, Any]:
    """Run one scenario; return its trace. Controller exceptions end the run and are recorded."""
    from trio._core import _run as trio_run  # noqa: PLC0415
    from trio.testing import MockClock  # noqa: PLC0415

    # trio shuffles runnable tasks; fix the order so traces are reproducible
    # (tests/__init__.py does the same when PYTHONHASHSEED is set)
    trio_run._r.seed(sc.seed)  # noqa: SLF001
    mclock = MockClock()

    trace: dict[str, Any] = {"scenario": sc.name, "doc": sc.doc}
    out = _Stdout()
    root = logging.getLogger()
    level = root.level
    root.setLevel(logging.WARNING)  # the controller logs every KV value at DEBUG
    with (
        mtime.patch_clock(time=_now),
        mock.patch.object(_dt, "datetime", _FakeDT),
        # the PIDs are called without a timestamp and read time.monotonic()
        mock.patch.object(_pid_impl, "time", _now),
        # several controller tasks wait on the same event; make their order stable
        mock.patch("trio._sync.Event.set", _event_set),
        mock.patch.object(trio_run, "_ALLOW_DETERMINISTIC_SCHEDULING", True),
        contextlib.redirect_stdout(out),
    ):
        try:
            anyio.run(
                _run,
                sc,
                trace,
                mclock,
                backend="trio",
                backend_options={"clock": mclock},
            )
        except BaseException as exc:
            while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
                exc = exc.exceptions[0]
            if isinstance(exc, KeyboardInterrupt):
                raise
            t = trace["samples"][-1]["t"] if trace.get("samples") else 0
            trace.setdefault("events", []).append([t, "exception", f"{type(exc).__name__}: {exc}"])
        finally:
            root.setLevel(level)
    return trace


def trace_file(name: str) -> FSPath:
    """Where a scenario's reference trace lives."""
    return TRACES / f"{name}.json"


def dump(trace: dict[str, Any]) -> str:
    """Serialise a trace: one sample per line, so diffs stay readable."""
    head = {k: v for k, v in trace.items() if k != "samples"}
    lines = [json.dumps(head, sort_keys=True)]
    lines += [json.dumps(s, sort_keys=True) for s in trace["samples"]]
    return "\n".join(lines) + "\n"


def load(text: str) -> dict[str, Any]:
    """Inverse of :func:`dump`."""
    first, *rest = text.splitlines()
    trace = json.loads(first)
    trace["samples"] = [json.loads(s) for s in rest]
    return trace


H = 3600

SCENARIOS = {
    sc.name: sc
    for sc in (
        Scenario(
            "cold_start",
            "Cold buffer, cold day: the heat pump starts up and warms the buffer.",
            6 * H,
            plant={"buffer": {"t_init": (32, 22)}, "weather": {"mean": 2, "amp": 3}},
            start=10 * H,
        ),
        Scenario(
            "steady",
            "Mild weather, warm buffer: normal cycling over half a day.",
            12 * H,
            plant={"buffer": {"t_init": (50, 35)}, "weather": {"mean": 6, "amp": 3}},
            start=8 * H,
        ),
        Scenario(
            "deice",
            "Cold, humid air: the heat pump ices up and de-ices while running.",
            6 * H,
            plant={
                "buffer": {"t_init": (35, 22)},
                "weather": {"mean": 1.5, "amp": 1, "rh_mean": 0.95, "rh_amp": 0},
            },
            start=10 * H,
        ),
        Scenario(
            "pellet_handover",
            "Heat pump running at +3 °C, frost down to -6 °C, then a thaw: the pellet "
            "burner starts, takes over, and hands back to the heat pump.",
            24 * H,
            plant={
                "buffer": {"t_init": (45, 30)},
                "weather": {
                    "sigma": 0.2,
                    "profile": (
                        (0, 3),
                        (3 * H, 3),
                        (6 * H, -6),
                        (14 * H, -6),
                        (18 * H, 6),
                        (24 * H, 8),
                    ),
                },
            },
            start=6 * H,
        ),
        Scenario(
            "day_night",
            "Evening to morning: night setback of the curve, then a forced day mode.",
            16 * H,
            plant={"buffer": {"t_init": (50, 30)}, "weather": {"mean": 3, "amp": 2}},
            start=18 * H,
            events=[(10 * H, "force_day", True), (12 * H, "force_day", False)],
        ),
        Scenario(
            "error_mid_run",
            "A heat-pump error while running, cleared an hour later.",
            5 * H,
            plant={"buffer": {"t_init": (32, 22)}, "weather": {"mean": 2, "amp": 1}},
            start=10 * H,
            events=[(2 * H, "error", (":2", 123)), (3 * H, "error", (":2", 0))],
        ),
        Scenario(
            "hp_no_power",
            "The running heat pump stops drawing power; its error is on ':1', "
            "which the legacy code ignores.",
            3 * H,
            plant={"buffer": {"t_init": (32, 22)}, "weather": {"mean": 2, "amp": 1}},
            start=10 * H,
            events=[(H, "error", (":1", 99))],
        ),
        Scenario(
            "bypass",
            "Manual bypass switched on while running, then off again.",
            4 * H,
            plant={"buffer": {"t_init": (32, 22)}, "weather": {"mean": 2, "amp": 1}},
            start=10 * H,
            events=[
                (H, "c_flow", 0.6),
                (H, "c_bypass_mode", 3),
                (H, "c_bypass_power", 0.5),
                (H, "c_bypass", True),
                (2 * H, "c_bypass", False),
            ],
        ),
    )
}


def main() -> None:
    """Regenerate reference traces: ``python -m tests.moat_dev_heat.legacy [NAME…]``."""
    names = sys.argv[1:] or list(SCENARIOS)
    TRACES.mkdir(parents=True, exist_ok=True)
    for n in names:
        tr = run_scenario(SCENARIOS[n])
        trace_file(n).write_text(dump(tr))
        print(n, len(tr["samples"]), "samples", *(e for e in tr["events"] if e[1] != "run"))


if __name__ == "__main__":
    main()
