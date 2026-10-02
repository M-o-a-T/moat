"""Run the slowest tests first, based on durations from previous runs.

Load it with ``-p moat.src.pytest_longfirst``, not from the ``tests``
package: importing that configures logging, which then prints to the
terminal before pytest starts capturing output.

Durations are kept in the pytest cache (key ``longfirst/durations``).
Sorting happens in pytest_collection_modifyitems, which runs on every
xdist worker; since all workers read the same cache the order is
identical, so xdist's "same collection" check passes.

``-n auto`` runs halfway between the physical and the logical number of
CPUs: that was measured to be faster than either. It is reduced so that
each worker gets at least `MIN_PER_WORKER` tests. The number of tests is
estimated from the recorded durations (see below), as collection hasn't
happened yet when the workers are started; ``-k`` is not considered. ``-n logical`` and
``PYTEST_XDIST_AUTO_NUM_WORKERS`` keep their usual meaning.

Use with ``--dist load --maxschedchunk 1`` so the controller hands out
tests one at a time instead of contiguous chunks (which would give all
the long tests to worker 0), or with ``--dist worksteal``.
"""

from __future__ import annotations

import json
import os
import pytest

KEY = "longfirst/durations"
MIN_PER_WORKER = 10


def _estimate_tests(config) -> int | None:
    """Count the known tests selected by the command line, or None if unknown."""
    root = config.rootpath
    # The cache plugin isn't set up yet, thus read the file directly.
    try:
        with (root / config.getini("cache_dir") / "v" / KEY).open() as f:
            known = json.load(f)
    except (OSError, ValueError):
        return None
    if not known:
        return None
    args = []
    for a in config.args or config.getini("testpaths") or ["."]:
        path, sep, rest = str(a).partition("::")
        try:
            path = os.path.relpath(os.path.abspath(path), root).rstrip("/")
        except ValueError:
            return None
        args.append(("" if path == "." else path) + sep + rest)

    def wanted(nodeid: str) -> bool:
        for a in args:
            if not a or nodeid == a or nodeid.startswith((a + "/", a + "::", a + "[")):
                return True
        return False

    return sum(1 for n in known if wanted(n))


def pytest_addoption(parser):
    """Add the ``--longfirst`` option."""
    parser.addoption("--longfirst", action="store_true", help="run slowest tests first")


@pytest.hookimpl(tryfirst=True)
def pytest_xdist_auto_num_workers(config):
    """``-n auto``: halfway between physical and logical CPUs."""
    if config.option.numprocesses != "auto" or os.environ.get("PYTEST_XDIST_AUTO_NUM_WORKERS"):
        return None
    try:
        import psutil  # noqa: PLC0415
    except ImportError:
        return None
    phys = psutil.cpu_count(logical=False)
    logi = psutil.cpu_count()
    if not phys or not logi:
        return None
    n = (phys + logi) // 2
    tests = _estimate_tests(config)
    if tests is not None:
        n = min(n, tests // MIN_PER_WORKER)
    return max(n, 1)


_new: dict[str, float] = {}


@pytest.hookimpl(trylast=True)
def pytest_collection_modifyitems(config, items):
    """Sort the items by descending duration of their previous run."""
    if not config.getoption("longfirst") or config.cache is None:
        return
    known = config.cache.get(KEY, {})
    if not known:
        return
    # unknown tests are assumed slow-ish: run them early-ish, after the known-slow ones
    default = sorted(known.values())[len(known) * 9 // 10]
    idx = {id(it): n for n, it in enumerate(items)}
    items.sort(key=lambda it: (-known.get(it.nodeid, default), idx[id(it)]))

    # worksteal hands worker k the k-th contiguous block of the list, so
    # deal the sorted list out round-robin: every block starts with its
    # share of the long tests.
    wi = getattr(config, "workerinput", None)
    if wi is not None and config.getoption("dist", None) == "worksteal":
        n = wi["workercount"]
        items[:] = [it for k in range(n) for it in items[k::n]]


def pytest_runtest_logreport(report):
    """Accumulate setup+call+teardown durations per test.

    On the xdist controller this also sees every worker's reports.
    """
    _new[report.nodeid] = _new.get(report.nodeid, 0.0) + report.duration


def pytest_sessionfinish(session):
    """Merge this run's durations into the cache."""
    config = session.config
    if config.cache is None or hasattr(config, "workerinput"):
        return  # only the controller (or a non-xdist run) writes the cache
    known = config.cache.get(KEY, {})
    known.update(_new)
    config.cache.set(KEY, known)
