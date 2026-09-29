"""
Convert MoaT-KV job records (``moat kv job``) to MoaT-Link job records.

MoaT-KV stores its jobs below ``kv.runner.prefix`` as
``any.GROUP.…``, ``at.NODE.GROUP.…`` and ``all.GROUP.…``; MoaT-Link uses
the same layout below ``link.job.prefix``. The record fields are the
same, so the conversion copies them and reports anything it can't
carry over: unknown fields, missing code snippets, and paths in the
job's ``data`` that don't exist in MoaT-Link.

Nothing in here writes to MoaT-KV. Writing to MoaT-Link only happens in
:func:`store_jobs`.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from moat.lib.path import P, Path

from collections.abc import Mapping
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.client import Link

    from collections.abc import Iterable
    from typing import Any

__all__ = [
    "FIELDS",
    "Job",
    "Report",
    "check_jobs",
    "convert",
    "kv_items",
    "read_kv",
    "store_jobs",
]

#: The job record fields both runners understand.
FIELDS = ("code", "data", "delay", "ok_after", "repeat", "backoff", "target", "info")

# Number of path elements before the job's own path, per mode.
_MODES = {"any": 2, "all": 2, "at": 3}


@dataclass
class Job:
    """A converted job record."""

    path: Path
    "Path below the job prefix, e.g. ``any.default.foo``."
    group: str
    "Mode and group (and node), e.g. ``any.default`` or ``at.NODE.GROUP``."
    record: dict[str, Any]
    notes: list[str] = field(default_factory=list)
    "Things to review for this job."


@dataclass
class Report:
    """What the converter found, and did."""

    jobs: list[Job] = field(default_factory=list)
    skipped: list[dict[str, Any]] = field(default_factory=list)
    "KV entries that are not job records."
    missing_code: dict[Path, list[Path]] = field(default_factory=dict)
    "Code snippet → jobs using it, for snippets not in MoaT-Link."
    missing_data: dict[Path, list[Path]] = field(default_factory=dict)
    "Data path → jobs referring to it, for paths not in MoaT-Link."
    kv_internal: dict[Path, list[Path]] = field(default_factory=dict)
    "Data path → jobs referring to it, for MoaT-KV internal paths (``:.moat…``)."
    stored: list[Path] = field(default_factory=list)
    unchanged: list[Path] = field(default_factory=list)
    conflicts: list[Path] = field(default_factory=list)
    "Jobs that already exist in MoaT-Link with different content."

    def dump(self) -> dict[str, Any]:
        """Return the report as a YAML-friendly dict."""

        def _users(d: dict[Path, list[Path]]) -> dict[Path, list[Path]]:
            return {k: sorted(v) for k, v in sorted(d.items())}

        counts: dict[str, int] = {}
        for j in self.jobs:
            counts[j.group] = counts.get(j.group, 0) + 1

        res: dict[str, Any] = {"jobs": len(self.jobs), "groups": dict(sorted(counts.items()))}
        notes = {j.path: j.notes for j in self.jobs if j.notes}
        if notes:
            res["notes"] = notes
        for k in ("skipped", "stored", "unchanged", "conflicts"):
            if v := getattr(self, k):
                res[k] = v
        if self.missing_code:
            res["missing_code"] = _users(self.missing_code)
        if self.missing_data:
            res["missing_data"] = _users(self.missing_data)
        if self.kv_internal:
            res["kv_internal"] = _users(self.kv_internal)
        return res


def kv_items(entries: Any) -> list[tuple[Path, Any]]:
    """
    Convert ``moat kv data PREFIX get -r`` output to ``(path, value)`` pairs.

    Both the list form (``-d`` not given: one ``{path: value}`` mapping per
    entry) and the nested dict form (values at ``_`` keys) are accepted.
    """
    res: list[tuple[Path, Any]] = []
    if isinstance(entries, Mapping):

        def _walk(d: Mapping, p: Path) -> None:
            for k, v in d.items():
                if k == "_":
                    res.append((p, v))
                elif isinstance(v, Mapping):
                    _walk(v, p | k)
                else:
                    raise ValueError(f"Not a 'get -r' tree at {p | k}: {v!r}")

        _walk(entries, Path())
        return res

    for e in entries:
        if not isinstance(e, Mapping) or len(e) != 1:
            raise ValueError(f"Not a 'get -r' entry: {e!r}")
        ((path, value),) = e.items()
        res.append((path if isinstance(path, Path) else P(path), value))
    return res


async def read_kv(cfg: Any) -> list[tuple[Path, Any]]:
    """
    Read the job records from MoaT-KV. Read-only.

    Args:
        cfg: The global configuration; uses ``kv`` and its ``runner.prefix``.

    Returns:
        ``(path, value)`` pairs, paths relative to the job prefix.
    """
    from moat.kv.client import open_client  # noqa: PLC0415

    prefix = cfg.kv.runner.prefix
    res = []
    async with open_client("moat.link.job.migrate", **cfg.kv) as client:
        async for r in client.get_tree(prefix, nchain=0):
            if "value" in r:
                res.append((r.path, r.value))
    return res


def _paths(data: Any) -> Iterable[Path]:
    """Yield all paths in some job data."""
    if isinstance(data, Path):
        yield data
    elif isinstance(data, Mapping):
        for v in data.values():
            yield from _paths(v)
    elif isinstance(data, list | tuple):
        for v in data:
            yield from _paths(v)


def convert(items: Iterable[tuple[Path, Any]]) -> Report:
    """
    Convert KV job records to Link job records.

    Args:
        items: ``(path, value)`` pairs, paths relative to the KV job prefix.
    """
    rep = Report()
    for path, value in items:
        mode = path[0] if len(path) else None
        n = _MODES.get(mode) if isinstance(mode, str) else None
        if n is None or len(path) <= n:
            rep.skipped.append({"path": path, "reason": "not a job path"})
            continue
        if not isinstance(value, Mapping) or "code" not in value:
            rep.skipped.append({"path": path, "reason": "no code"})
            continue

        job = Job(path=path, group=str(Path.build(path[:n])), record={})
        for k, v in value.items():
            if k in FIELDS:
                job.record[k] = v
            else:
                job.notes.append(f"dropped field {k!r}: {v!r}")
        if not isinstance(job.record["code"], Path):
            job.record["code"] = P(job.record["code"])
        if job.record.get("data") is None:
            job.record["data"] = {}
        rep.jobs.append(job)
    return rep


async def check_jobs(conn: Link, rep: Report) -> None:
    """
    Check the converted jobs' code and data paths against MoaT-Link.

    Only reads from MoaT-Link.
    """
    from moat.link.code import CODE_EXEC_ROOT  # noqa: PLC0415

    found: dict[Path, bool] = {}

    async def exists(p: Path) -> bool:
        try:
            return found[p]
        except KeyError:
            pass
        try:
            await conn.d_get(p)
        except KeyError:
            res = False
        else:
            res = True
        found[p] = res
        return res

    for job in rep.jobs:
        code = job.record["code"]
        if not await exists(CODE_EXEC_ROOT + code):
            rep.missing_code.setdefault(code, []).append(job.path)
        for p in _paths(job.record["data"]):
            if len(p) and isinstance(p[0], str) and p[0].startswith("."):
                rep.kv_internal.setdefault(p, []).append(job.path)
            elif not await exists(p):
                rep.missing_data.setdefault(p, []).append(job.path)


async def store_jobs(conn: Link, prefix: Path, rep: Report, force: bool = False) -> None:
    """
    Write the converted jobs to MoaT-Link, below ``prefix``.

    Existing records with the same content are left alone; different
    ones are only replaced if ``force`` is set.
    """
    for job in rep.jobs:
        p = prefix + job.path
        try:
            old = await conn.d_get(p)
        except KeyError:
            pass
        else:
            if old == job.record:
                rep.unchanged.append(job.path)
                continue
            if not force:
                rep.conflicts.append(job.path)
                continue
        await conn.d_set(p, job.record)
        rep.stored.append(job.path)
