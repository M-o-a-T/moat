"""
Traces: sampled records of a simulation run, and their comparison.

A trace is a header (name, description, events) plus samples, one dict
per sample with ``t`` (seconds since the start). On disk it is JSON
lines: the header, then one line per sample, so diffs stay readable.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.lib.path import Path

    from .loop import ClosedLoop

    from collections.abc import Mapping

__all__ = ["Trace", "compare", "dump", "load"]


def _r(v: Any) -> Any:
    if isinstance(v, float):
        return round(v, 3)
    if isinstance(v, (list, tuple)):
        return [_r(x) for x in v]
    if isinstance(v, dict):
        return {str(k): _r(x) for k, x in v.items()}
    return v


def dump(trace: Mapping[str, Any]) -> str:
    """Serialise a trace (a dict with ``samples``); floats are rounded to 3 places."""
    head = {k: _r(v) for k, v in trace.items() if k != "samples"}
    lines = [json.dumps(head, sort_keys=True)]
    lines += [json.dumps(_r(s), sort_keys=True) for s in trace["samples"]]
    return "\n".join(lines) + "\n"


def load(text: str) -> dict[str, Any]:
    """Inverse of :func:`dump`."""
    first, *rest = text.splitlines()
    trace = json.loads(first)
    trace["samples"] = [json.loads(s) for s in rest]
    return trace


def _same(a: Any, b: Any, tol: float) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return abs(a - b) <= tol
    return a == b


def compare(
    ref: Mapping[str, Any],
    cur: Mapping[str, Any],
    tol: float | Mapping[str, float] = 0.002,
    max_diffs: int = 50,
) -> list[str]:
    """
    Compare two traces (as returned by :func:`load`).

    Args:
        ref: The reference trace.
        cur: The trace under test.
        tol: Absolute tolerance for numbers, overall or per sample key
            (missing keys: 0.002).
        max_diffs: Stop after this many differences.

    Returns:
        Human-readable differences; empty if the traces match.
    """
    diffs: list[str] = []
    if ref.get("events") != cur.get("events"):
        diffs.append(f"events differ:\n  ref {ref.get('events')}\n  cur {cur.get('events')}")
    rs, cs = ref["samples"], cur["samples"]
    if len(rs) != len(cs):
        diffs.append(f"sample count differs: ref {len(rs)}, cur {len(cs)}")
    for r, c in zip(rs, cs, strict=False):
        for k in sorted(r.keys() | c.keys()):
            t = tol.get(k, 0.002) if not isinstance(tol, (int, float)) else tol
            if not _same(r.get(k), c.get(k), t):
                diffs.append(f"t={r.get('t')} {k}: ref {r.get(k)!r}, cur {c.get(k)!r}")
                if len(diffs) >= max_diffs:
                    diffs.append("(more differences not shown)")
                    return diffs
    return diffs


@dataclass
class Trace:
    """
    Records a :class:`~moat.dev.heat.sim.loop.ClosedLoop` run.

    Pass :meth:`record` as the loop's callback.

    Args:
        name: The scenario's name.
        doc: What the scenario does.
        paths: Sample key → bus path to record.
        plant: Plant sensor names (exact values) to record.
        every: Sampling interval, seconds.
    """

    name: str
    doc: str = ""
    paths: Mapping[str, Path] = field(default_factory=dict)
    plant: tuple[str, ...] = ()
    every: float = 60
    samples: list[dict[str, Any]] = field(default_factory=list)
    events: list[list[Any]] = field(default_factory=list)
    _next: float = 0

    def event(self, t: float, what: str, value: Any = None) -> None:
        """Note an event."""
        self.events.append([round(t), what, value])

    def record(self, loop: ClosedLoop) -> None:
        """Take a sample if one is due."""
        if loop.now + 1e-6 < self._next:
            return
        self._next = loop.now + self.every
        row: dict[str, Any] = {"t": round(loop.now)}
        for k, p in self.paths.items():
            row[k] = loop.get(p)
        if self.plant:
            truth = loop.plant.truth()
            for k in self.plant:
                row[k] = truth[k]
        self.samples.append(row)

    def as_dict(self) -> dict[str, Any]:
        """The trace in the form :func:`dump` takes."""
        return {
            "scenario": self.name,
            "doc": self.doc,
            "events": self.events,
            "samples": self.samples,
        }

    def dump(self) -> str:
        """Serialise."""
        return dump(self.as_dict())
