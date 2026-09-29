"""
Side-car recorder and open-loop replay (HEAT.md §4.3).

``moat dev heat record save`` watches MoaT-Link subtrees and writes a
timeline; ``moat dev heat record replay`` writes that timeline back into
a MoaT-Link tree, e.g. a test server, so that a unit's decisions can be
checked against recorded inputs. Replay is open loop: the recorded plant
does not react to the replayed unit's outputs, so only use it for
regression tests of individual decision cores. ``moat dev heat record
convert-legacy`` turns a recording of the legacy controller
(``solvis.py run -r``) into a timeline.

A timeline is a stream of YAML documents: a header mapping
(``{moat.dev.heat.record: 1, start: <wall-clock time>, paths: [...]}``),
then ``[t, path, value]`` per change, ``t`` in seconds since the start;
``[t, path]`` means the item was deleted.
"""

from __future__ import annotations

import anyio
import sys
from contextlib import nullcontext

import asyncclick as click

from moat.util import MsgReader, NotGiven, yprint
from moat.lib.path import P, Path
from moat.util.time import time

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, TextIO

if TYPE_CHECKING:
    from moat.link.client import LinkSender

    from collections.abc import AsyncIterator, Iterable, Iterator

__all__ = [
    "DEFAULT_PATHS",
    "HEADER",
    "LEGACY_PATHS",
    "Event",
    "cli",
    "convert_legacy",
    "read_timeline",
    "record",
    "replay",
]

HEADER = "moat.dev.heat.record"
"""Key of the header document; its value is the format version."""

DEFAULT_PATHS = (P("heat.s"), P("app.heat"), P("temp"), P("home.ass.dyn"))
"""Subtrees recorded by default."""

Event = tuple[float, Path, Any]
"""A change of one item as ``(t, path, value)``: seconds since the start, path, new value
(`NotGiven` if deleted)."""

LEGACY_PATHS: dict[str, Path] = {
    "c_flow": P("heat.s.pump.rate.cmd"),
    "c_bypass": P("home.ass.dyn.switch.heizung.wp_bypass.cmd"),
    "c_bypass_mode": P("heat.s.pump.cmd.want.mode"),
    "c_bypass_power": P("heat.s.pump.cmd.want.power"),
    "cm_wp": P("home.ass.dyn.switch.heizung.wp.cmd"),
    "cm_heat": P("home.ass.dyn.switch.heizung.main.cmd"),
    "cm_pellet": P("heat.s.pellets.power.cmd"),
    "cm_pellet_force": P("heat.s.pellets.load.force"),
    "c_heat": P("heat.s.heat.temp"),
    "c_heat_night": P("heat.s.heat.temp_low"),
    "c_water": P("heat.s.water.temp"),
    "t_in": P("heat.s.pump.temp.in"),
    "t_out": P("heat.s.pump.temp.out"),
    "t_heat": P("heat.s.heating.temp.out"),
    "r_flow": P("heat.s.pump.flow"),
    "m_ice": P("heat.s.pump.de_ice"),
    "m_cop": P("home.ass.dyn.sensor.heizung.wp_cop.state"),
    "m_pellet_state": P("heat.s.pellets.state"),
    "tb_water": P("heat.s.buffer.temp.water"),
    "tb_heat": P("heat.s.buffer.temp.heat"),
    "tb_mid": P("heat.s.buffer.temp.mid"),
    "tb_low": P("heat.s.buffer.temp.return"),
    "m_power": P("heat.s.pump.power"),
    "m_air": P("home.ass.dyn.sensor.temp.garten_kompost_schatten.state"),
    "m_air_pred": P("temp.min.forecast:6"),
    "m_pellet": P("heat.s.pellets.temp.top"),
    "m_switch": P("heat.s.pump.switchover"),
}
"""The legacy controller's input attributes and their MoaT-Link paths (PATHS.md)."""


def _write(out: TextIO, doc: Any) -> None:
    yprint(doc, stream=out)
    print("---", file=out)
    out.flush()


async def record(
    link: LinkSender,
    out: TextIO,
    paths: Iterable[Path] = DEFAULT_PATHS,
    *,
    task_status: Any = anyio.TASK_STATUS_IGNORED,
) -> None:
    """
    Record the current state of some subtrees, then every change, until cancelled.

    Args:
        link: The MoaT-Link client.
        out: Where to write the timeline.
        paths: The subtrees to record.
    """
    paths = list(paths)
    t0 = anyio.current_time()
    _write(out, {HEADER: 1, "start": time(), "paths": paths})

    async def watch(root: Path, *, task_status: Any) -> None:
        async with link.d_watch(root, subtree=True, mark=True) as mon:
            async for msg in mon:
                if msg is None:
                    task_status.started()
                    continue
                p, v = msg
                t = round(anyio.current_time() - t0, 3)
                _write(out, [t, root + p] if v is NotGiven else [t, root + p, v])

    async with anyio.create_task_group() as tg:
        for p in paths:
            await tg.start(watch, p)
        task_status.started()


async def read_timeline(path: str) -> AsyncIterator[Event]:
    """
    Read a timeline file.

    Args:
        path: The file, or ``-`` for standard input.
    """
    async with MsgReader(path=path, codec="yaml") as rd:
        async for doc in rd:
            if isinstance(doc, Mapping):
                if HEADER not in doc:
                    raise ValueError(f"Not a timeline: {doc!r}")
                continue
            t, p, *v = doc
            yield float(t), p if isinstance(p, Path) else P(p), v[0] if v else NotGiven


async def replay(
    link: LinkSender,
    events: AsyncIterator[Event] | Iterable[Event],
    *,
    speed: float = 1.0,
    prefix: Path | None = None,
) -> int:
    """
    Write a timeline into MoaT-Link, as retained values, at the recorded pace.

    Args:
        link: The MoaT-Link client.
        events: The timeline.
        speed: Replay this many times faster; 0: as fast as possible.
        prefix: Prepended to every path.

    Returns:
        The number of events written.
    """
    t0 = anyio.current_time()
    n = 0

    async def _one(t: float, p: Path, v: Any) -> None:
        nonlocal n
        if speed:
            await anyio.sleep_until(t0 + t / speed)
        if prefix is not None:
            p = prefix + p
        await link.d_set(p, v, retain=True)
        n += 1

    if hasattr(events, "__aiter__"):
        async for t, p, v in events:  # ty:ignore[not-iterable]
            await _one(t, p, v)
    else:
        for t, p, v in events:
            await _one(t, p, v)
    return n


def convert_legacy(
    docs: Iterable[Any], paths: Mapping[str, Path] = LEGACY_PATHS
) -> Iterator[Event]:
    """
    Convert a legacy recording (one ``Data`` snapshot per YAML document,
    with ``TS``, the monotonic time) into a timeline.

    The first snapshot yields every known input; later ones only the
    inputs that changed. Attributes without a path are ignored.

    Args:
        docs: The recording's documents.
        paths: Legacy attribute → MoaT-Link path.
    """
    last: dict[str, Any] = {}
    ts0: float | None = None
    for d in docs:
        if not isinstance(d, Mapping) or "TS" not in d:
            continue
        if ts0 is None:
            ts0 = d["TS"]
        t = round(d["TS"] - ts0, 3)
        for k, p in paths.items():
            if k not in d:
                continue
            v = d[k]
            if k in last and last[k] == v:
                continue
            last[k] = v
            yield t, p, v


def _paths(paths: tuple[str, ...]) -> list[Path]:
    return [P(p) for p in paths] if paths else list(DEFAULT_PATHS)


@click.group(short_help="Record and replay MoaT-Link timelines.")
async def cli() -> None:
    """Record MoaT-Link subtrees, and replay the recording (open loop)."""


@cli.command("save", short_help="Record MoaT-Link subtrees to a timeline.")
@click.option("-o", "--output", type=click.File("w"), default="-", help="The timeline file.")
@click.option("-t", "--time", "duration", type=float, help="Stop after this many seconds.")
@click.argument("paths", nargs=-1)
@click.pass_obj
async def save(obj: Any, output: TextIO, duration: float | None, paths: tuple[str, ...]) -> None:
    """
    Record the current state of some MoaT-Link subtrees, then every change.

    The default subtrees are ``heat.s``, ``app.heat``, ``temp`` and
    ``home.ass.dyn``.
    """
    from moat.link.client import Link  # noqa: PLC0415

    async with Link(obj.cfg.link) as link:
        with anyio.move_on_after(duration) if duration else nullcontext():
            await record(link, output, _paths(paths))


@cli.command("replay", short_help="Replay a timeline into MoaT-Link.")
@click.option("-s", "--speed", type=float, default=1.0, help="Faster by this factor; 0: at once.")
@click.option("-p", "--prefix", type=P, help="Write below this path, e.g. a test tree.")
@click.argument("timeline", type=click.Path(exists=True, dir_okay=False, allow_dash=True))
@click.pass_obj
async def replay_(obj: Any, speed: float, prefix: Path | None, timeline: str) -> None:
    """
    Write a recorded timeline into MoaT-Link, as retained values.

    This is open loop: nothing reacts to what the units do in response.
    Use a test server, or ``--prefix``, never the production tree.
    """
    from moat.link.client import Link  # noqa: PLC0415

    async with Link(obj.cfg.link) as link:
        n = await replay(link, read_timeline(timeline), speed=speed, prefix=prefix)
    print(n, "events", file=sys.stderr)


@cli.command("convert-legacy", short_help="Convert a legacy recording to a timeline.")
@click.argument("recording", type=click.File("r"))
@click.option("-o", "--output", type=click.File("w"), default="-", help="The timeline file.")
async def convert(recording: TextIO, output: TextIO) -> None:
    """
    Convert a recording of the legacy controller (``solvis.py run -r``) to a timeline.
    """
    from moat.util import yload  # noqa: PLC0415

    paths = [LEGACY_PATHS[k] for k in sorted(LEGACY_PATHS)]
    _write(output, {HEADER: 1, "start": None, "paths": paths})
    for t, p, v in convert_legacy(yload(recording, multi=True)):
        _write(output, [t, p, v])
