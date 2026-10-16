"""Tests for `LinkSender.retrying`.

The retry helper combines `stamina`'s exponential back-off with the MoaT-Link
error-reporting subsystem (:meth:`e_exc` / :meth:`e_ok`). These tests exercise
it in isolation by constructing a bare `LinkSender` whose ``e_ok`` / ``e_exc``
methods are replaced with recording stubs, so no server or MQTT broker is
needed.

`stamina.set_testing` is used to disable the real back-off sleeps and to cap
the number of attempts, keeping the tests fast and deterministic.
"""

from __future__ import annotations

import anyio
import logging
import pytest
from functools import partial

import stamina

from moat.util import ungroup
from moat.lib.path import P
from moat.link.client import LinkSender


class _DummyLink:
    """Minimal stand-in for a `LinkCommon`."""

    def __init__(self) -> None:
        self.name = "T"
        self.logger = logging.getLogger("tests.moat_link.test_retrying")
        self.announced: dict = {}


def _mk_sender():
    """Build a `LinkSender` with recording ``e_ok`` / ``e_exc`` stubs.

    Returns the sender plus the lists of recorded calls.
    """
    sender = LinkSender(_DummyLink())
    oks: list = []
    excs: list = []

    async def e_ok(path, **kw):
        oks.append((path, kw))

    async def e_exc(path, exc, **kw):
        excs.append((path, ungroup.one(exc), kw))

    sender.e_ok = e_ok  # type: ignore[method-assign]
    sender.e_exc = e_exc  # type: ignore[method-assign]
    return sender, oks, excs


# Small retry config used throughout: no real waiting, bounded attempts.
_CFG = {
    "up": 0.01,
    "wait": 0.5,
    "initial": 0.0,
    "max": 0.0,
    "jitter": 0.0,
}


@pytest.fixture(autouse=True)
def _fast_stamina():
    """Disable stamina's real sleeping and cap attempts for every test."""
    with stamina.set_testing(True, attempts=20, cap=True):
        yield


def _unwrap(exc: BaseException) -> BaseException:
    """Collapse single-element exception groups for easier assertion."""
    return ungroup.one(exc)


@pytest.mark.anyio
async def test_success_reports_ok_once():
    """A proc that starts and stays up is reported as OK exactly once."""
    sender, oks, excs = _mk_sender()

    async def proc(*, task_status):
        task_status.started("hi")
        await anyio.sleep_forever()

    async with anyio.create_task_group() as tg:
        tg.start_soon(sender.retrying, _CFG, P("svc.a"), proc)
        # Give the attempt time to start, pass the `up` window, and report.
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    assert len(oks) == 1
    assert oks[0][0] == P("svc.a")
    assert oks[0][1]["value"] == "hi"
    assert excs == []


@pytest.mark.anyio
async def test_transient_failure_is_retried_then_ok():
    """A tolerated error is reported and retried; eventual success reports OK."""
    sender, oks, excs = _mk_sender()
    n = {"i": 0}

    async def proc(*, task_status):
        n["i"] += 1
        if n["i"] < 3:
            raise OSError(f"boom {n['i']}")
        task_status.started("up")
        await anyio.sleep_forever()

    async with anyio.create_task_group() as tg:
        tg.start_soon(sender.retrying, _CFG, P("svc.b"), proc)
        await anyio.sleep(0.3)
        tg.cancel_scope.cancel()

    assert n["i"] == 3
    assert len(excs) == 2
    assert all(isinstance(e, OSError) for _, e, _ in excs)
    assert len(oks) == 1
    assert oks[0][1]["value"] == "up"


@pytest.mark.anyio
async def test_non_tolerated_exception_falls_through():
    """An exception outside the `on` set is reported once and propagates."""
    sender, oks, excs = _mk_sender()
    n = {"i": 0}

    async def proc(*, task_status):  # noqa: ARG001
        n["i"] += 1
        raise TypeError("fatal")

    raised: list[BaseException] = []
    try:
        await sender.retrying(_CFG, P("svc.c"), proc)
    except BaseException as exc:
        raised.append(_unwrap(exc))

    # Not retried: exactly one attempt, one report, no OK.
    assert n["i"] == 1
    assert len(excs) == 1
    assert isinstance(excs[0][1], TypeError)
    assert oks == []
    assert len(raised) == 1
    assert isinstance(raised[0], TypeError)


@pytest.mark.anyio
async def test_extra_tolerated_exceptions_are_added():
    """Caller-supplied `on` exceptions are honored alongside the defaults."""
    sender, oks, excs = _mk_sender()
    n = {"i": 0}

    async def proc(*, task_status):
        n["i"] += 1
        if n["i"] == 1:
            raise ValueError("custom-tolerated")
        task_status.started()
        await anyio.sleep_forever()

    cfg = {**_CFG, "on": (ValueError,)}
    async with anyio.create_task_group() as tg:
        tg.start_soon(sender.retrying, cfg, P("svc.d"), proc)
        await anyio.sleep(0.3)
        tg.cancel_scope.cancel()

    # ValueError was tolerated -> retried -> succeeded on attempt 2.
    assert n["i"] == 2
    assert len(excs) == 1
    assert isinstance(excs[0][1], ValueError)
    assert len(oks) == 1


@pytest.mark.anyio
async def test_callback_on_predicate():
    """A callable `on` is used as stamina's back-off hook."""
    sender, oks, excs = _mk_sender()
    seen: list = []
    n = {"i": 0}

    def hook(exc):
        seen.append(type(exc))
        # Retry only ValueError, not KeyError.
        return isinstance(exc, ValueError)

    async def proc(*, task_status):
        n["i"] += 1
        if n["i"] == 1:
            raise ValueError("retry me")
        if n["i"] == 2:
            raise KeyError("do not retry")
        task_status.started()
        await anyio.sleep_forever()

    cfg = {**_CFG, "on": hook}
    raised: list[BaseException] = []
    try:
        await sender.retrying(cfg, P("svc.e"), proc)
    except BaseException as exc:
        raised.append(_unwrap(exc))

    assert n["i"] == 2
    assert seen == [ValueError, KeyError]
    assert len(excs) == 2
    assert oks == []
    assert isinstance(raised[0], KeyError)


@pytest.mark.anyio
async def test_attempts_limit_is_respected():
    """When attempts run out the last error propagates."""
    sender, oks, excs = _mk_sender()
    n = {"i": 0}

    async def proc(*, task_status):  # noqa: ARG001
        n["i"] += 1
        raise OSError("always")

    cfg = {**_CFG, "attempts": 3}
    raised: list[BaseException] = []
    try:
        await sender.retrying(cfg, P("svc.f"), proc)
    except BaseException as exc:
        raised.append(_unwrap(exc))

    assert n["i"] == 3
    assert len(excs) == 3
    assert oks == []
    assert isinstance(raised[0], OSError)


@pytest.mark.anyio
async def test_wait_timeout_is_reported_and_propagates():
    """Failure to signal readiness within `wait` aborts the attempt."""
    sender, oks, excs = _mk_sender()

    async def proc(*, task_status):  # noqa: ARG001
        # Never calls task_status.started().
        await anyio.sleep_forever()

    cfg = {**_CFG, "wait": 0.02, "attempts": 2}
    raised: list[BaseException] = []
    try:
        await sender.retrying(cfg, P("svc.g"), proc)
    except BaseException as exc:
        raised.append(_unwrap(exc))

    # TimeoutError is a subclass of OSError, hence tolerated and retried.
    assert len(excs) == 2
    assert all(isinstance(e, TimeoutError) for _, e, _ in excs)
    assert oks == []
    assert isinstance(raised[0], TimeoutError)


@pytest.mark.anyio
async def test_proc_args_forwarded():
    """Positional and keyword args are forwarded to proc."""
    sender, oks, _excs = _mk_sender()
    received: list = []

    async def proc(a, b, *, c, task_status):
        received.append((a, b, c))
        task_status.started()
        await anyio.sleep_forever()

    async with anyio.create_task_group() as tg:
        tg.start_soon(partial(sender.retrying, _CFG, P("svc.h"), proc, 1, 2, c=3))
        await anyio.sleep(0.2)
        tg.cancel_scope.cancel()

    assert received == [(1, 2, 3)]
    assert len(oks) == 1


@pytest.mark.anyio
async def test_none_cfg_uses_defaults():
    """``cfg=None`` does not crash and behaves like the default config."""
    sender, _oks, excs = _mk_sender()

    async def proc(*, task_status):
        task_status.started()
        await anyio.sleep_forever()

    # Use a tiny explicit `up` via a fresh dict so the test stays fast even
    # though None pulls in the (large) default `up`/`wait`.
    # Instead, drive retrying with None but override nothing else: rely on
    # stamina test mode to skip sleeps, and cancel before the long `up`.
    async with anyio.create_task_group() as tg:
        tg.start_soon(sender.retrying, None, P("svc.i"), proc)
        await anyio.sleep(0.1)
        tg.cancel_scope.cancel()

    # The proc started; with the default huge `up` we cancel before e_ok,
    # so we only assert no exception escaped and no erroneous e_exc fired.
    assert excs == []


@pytest.mark.anyio
async def test_reporting_failure_does_not_mask_original():
    """If e_exc itself raises, the original exception still propagates."""
    sender, _oks, _excs = _mk_sender()

    async def bad_e_exc(path, exc, **kw):  # noqa: ARG001
        raise RuntimeError("reporter broke")

    sender.e_exc = bad_e_exc  # type: ignore[method-assign]

    async def proc(*, task_status):  # noqa: ARG001
        raise OSError("original")

    raised: list[BaseException] = []
    try:
        await sender.retrying({**_CFG, "attempts": 1}, P("svc.j"), proc)
    except BaseException as exc:
        raised.append(_unwrap(exc))

    # The original OSError must survive (shielded reporting moves on).
    assert len(raised) == 1
    assert isinstance(raised[0], OSError)
