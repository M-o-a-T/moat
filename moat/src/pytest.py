"""Run the slowest tests first, based on durations from previous runs.

Load it with ``-p moat.src.pytest_longfirst``, not from the ``tests``
package: importing that configures logging, which then prints to the
terminal before pytest starts capturing output.

Durations are kept in the pytest cache (key ``longfirst/durations``).
Sorting happens in pytest_collection_modifyitems, which runs on every
xdist worker; since all workers read the same cache the order is
identical, so xdist's "same collection" check passes.

Use with ``--dist load --maxschedchunk 1`` so the controller hands out
tests one at a time instead of contiguous chunks (which would give all
the long tests to worker 0), or with ``--dist worksteal``.
"""

from __future__ import annotations

import pytest

KEY = "longfirst/durations"


def pytest_addoption(parser):
    """Add the ``--longfirst`` option."""
    parser.addoption("--longfirst", action="store_true", help="run slowest tests first")


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
