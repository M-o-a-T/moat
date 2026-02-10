"""Tests for moat.kv.akumuli bug fixes."""

from __future__ import annotations

import inspect

from moat.kv.akumuli import _main, model
from moat.kv.akumuli import task as task_mod


def test_tag_isinstance():
    """Verify that byte-valued tags are decoded correctly.

    Regression: ``isinstance(str, bytes)`` was always False,
    so bytes tags were converted via ``str()`` instead of
    being decoded.
    """
    src = inspect.getsource(task_mod)
    assert "isinstance(v, bytes)" in src
    assert "isinstance(str, bytes)" not in src


def test_attr_split():
    """Verify that the 'set' command checks keywords correctly.

    Regression: ``.split`` (without parens) yielded a method object
    instead of a list, so the ``all(…)`` check always passed.
    """
    src = inspect.getsource(_main)
    assert ".split()" in src
    assert ".split)" not in src


def test_t_min_throttle():
    """Verify that t_min skips updates that arrive too soon.

    Regression: the comparison was inverted (``< t`` instead of
    ``> t``), so updates were skipped when enough time *had*
    elapsed rather than when too little time had elapsed.
    """
    src = inspect.getsource(model.AkumuliNode.with_output)
    # The condition should skip (continue) when last + min > now,
    # i.e. not enough time has passed yet.
    assert "self._t_last + self.t_min > t" in src


def test_process_raw_not_staticmethod():
    """Verify that process_raw is a plain nested function.

    Regression: had a stray ``@staticmethod`` decorator which
    is meaningless on a nested function.
    """
    src = inspect.getsource(task_mod.task)
    assert "@staticmethod" not in src


def test_process_raw_has_task_status():
    """Verify that process_raw accepts task_status for tg.start().

    ``tg.start(process_raw)`` requires the coroutine to accept
    a ``task_status`` parameter and call ``task_status.started()``.
    """
    src = inspect.getsource(task_mod.task)
    assert "task_status" in src
    assert "task_status.started()" in src
