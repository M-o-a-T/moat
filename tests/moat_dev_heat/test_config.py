"""
Tests for the heat controller's configuration loader.
"""

from __future__ import annotations

import anyio
import pytest
from contextlib import asynccontextmanager

from moat.util import NotGiven, attrdict
from moat.dev.heat import config as hcfg
from moat.dev.heat.config import CFG_PATH, ServiceCfg, UnitCfg, unit_config
from moat.lib.config.base import BaseModel
from moat.link._test import Scaffold

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.client import LinkSender

    from collections.abc import AsyncIterator

pytestmark = [pytest.mark.anyio, pytest.mark.usefixtures("dflt")]

UNIT = "test"


class Inner(BaseModel):
    "nested part of the test config"

    a: int = 1
    b: int = 2


class TCfg(UnitCfg):
    "test config"

    x: int = 0
    inner: Inner = Inner()


@pytest.fixture
def dflt(monkeypatch: pytest.MonkeyPatch) -> attrdict:
    "package defaults of the test unit"
    d = attrdict(x=1, inner=attrdict(a=10, b=20))
    orig = hcfg.defaults
    monkeypatch.setattr(hcfg, "defaults", lambda unit: d if unit == UNIT else orig(unit))
    return d


class Cfgs:
    "collects the configs yielded by `unit_config`"

    def __init__(self, link: LinkSender):
        self.link = link
        self.w, self.r = anyio.create_memory_object_stream[TCfg](10)

    async def run(self, *, task_status=anyio.TASK_STATUS_IGNORED) -> None:
        "feed the stream"
        task_status.started()
        async for cfg in unit_config(self.link, UNIT, TCfg):
            await self.w.send(cfg)

    async def next(self) -> TCfg:
        "the next config"
        with anyio.fail_after(2):
            return await self.r.receive()

    async def none(self) -> None:
        "assert that no config arrives"
        with anyio.move_on_after(0.3):
            cfg = await self.r.receive()
            raise AssertionError(f"Unexpected config: {cfg!r}")


@asynccontextmanager
async def _setup(cfg: dict) -> AsyncIterator[tuple[LinkSender, Cfgs]]:
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={}),
        sf.client_() as c,
    ):
        yield c, Cfgs(c)


async def _set(c: LinkSender, data: object) -> None:
    await c.d_set(CFG_PATH / UNIT, data, retain=True, verify=False)
    await c.i_sync()


async def test_defaults_only(cfg):
    "no Link item: the package defaults"
    async with _setup(cfg) as (_c, cf), anyio.create_task_group() as tg:
        await tg.start(cf.run)
        res = await cf.next()
        assert res.x == 1
        assert res.inner.a == 10
        assert res.inner.b == 20
        tg.cancel_scope.cancel()


async def test_partial_override(cfg):
    "a partial Link item overrides nested keys only"
    async with _setup(cfg) as (c, cf):
        await _set(c, {"inner": {"b": 5}})
        async with anyio.create_task_group() as tg:
            await tg.start(cf.run)
            res = await cf.next()
            assert res.x == 1
            assert res.inner.a == 10
            assert res.inner.b == 5
            tg.cancel_scope.cancel()


async def test_live_update_invalid_delete(cfg):
    "live update, invalid update ignored, deletion reverts to defaults"
    async with _setup(cfg) as (c, cf), anyio.create_task_group() as tg:
        await tg.start(cf.run)
        assert (await cf.next()).x == 1

        await _set(c, {"x": 3})
        assert (await cf.next()).x == 3

        await _set(c, {"x": "bad"})
        await cf.none()

        await _set(c, {"x": 4, "inner": {"a": 7}})
        res = await cf.next()
        assert res.x == 4
        assert res.inner.a == 7

        await _set(c, NotGiven)
        res = await cf.next()
        assert res.x == 1
        assert res.inner.a == 10
        tg.cancel_scope.cancel()


async def test_invalid_initial(cfg):
    "an invalid item at startup yields the defaults"
    async with _setup(cfg) as (c, cf):
        await _set(c, {"x": "bad"})
        async with anyio.create_task_group() as tg:
            await tg.start(cf.run)
            assert (await cf.next()).x == 1
            tg.cancel_scope.cancel()


def test_package_defaults(cfg):  # noqa: ARG001
    "the shipped defaults validate"
    assert ServiceCfg.model_validate(hcfg.defaults("service")).host == "heat"
