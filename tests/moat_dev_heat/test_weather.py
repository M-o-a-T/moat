"""
Tests for the minimum-temperature forecast job (examples/moat-dev-heat).
"""

from __future__ import annotations

import anyio
import logging
import pytest
from functools import partial
from pathlib import Path as FSPath

import httpx

from moat.util import yload
from moat.lib.path import P, Path
from moat.link.code.run import Code
from moat.link.job.runner import _CLASSES

from typing import Any

CODE = FSPath(__file__).parents[2] / "examples" / "moat-dev-heat" / "code.weather.min-temp.yaml"
DST = P("test.temp.min.forecast")
KEY = P("test.weather.key")
HORIZONS = (4, 5, 6, 10, 12, 18, 24)


class _Link:
    "records writes"

    def __init__(self) -> None:
        self.writes: list[tuple[Any, Any]] = []

    async def d_set(self, path, value):
        self.writes.append((path, value))


class _Timer:
    def __init__(self, adm: _Self) -> None:
        self.adm = adm

    async def run(self, delay: float) -> None:
        self.adm.timed.send_nowait(delay)

    def cancel(self) -> bool:
        return True


class _Self:
    "the job runner's call admin: records watches, reports timer (re)starts"

    def __init__(self) -> None:
        self.done = 0
        self.watches: dict[Path, type] = {}
        self.timed, self.timer_calls = anyio.create_memory_object_stream[float](10)

    async def setup_done(self) -> None:
        self.done += 1

    async def watch(self, path: Path, fetch: bool = True, cls: type = _CLASSES.ChangeMsg):  # noqa: ARG002
        self.watches[path] = cls

    async def timer(self, delay: float) -> _Timer:
        t = _Timer(self)
        await t.run(delay)
        return t


class Job:
    "runs the stored code against a canned forecast"

    def __init__(self, monkeypatch, key: Any) -> None:
        self.temps = [5.0, 4.0, 6.0, 3.5, 7.0, 8.0, 2.0] + [9.0] * 20
        self.calls: list[httpx.Request] = []
        monkeypatch.setattr(
            httpx,
            "AsyncClient",
            partial(httpx.AsyncClient, transport=httpx.MockTransport(self._handle)),
        )
        self.link, self.adm = _Link(), _Self()
        self.info, self._info = anyio.create_memory_object_stream[Any](10)
        self.code = Code(self.link, P("weather.min-temp"))
        self.code.update(yload(CODE.read_text()), compile=True)
        self.key = key

    def _handle(self, req: httpx.Request) -> httpx.Response:
        self.calls.append(req)
        return httpx.Response(200, json={"hourly": [{"temp": t} for t in self.temps]})

    async def run(self) -> None:
        "the job, as the runner calls it"
        await self.code(
            key=self.key,
            lat=49.46,
            lon=11.11,
            dst=DST,
            interval=600,
            _link=self.link,
            _self=self.adm,
            _info=self._info,
            _cls=_CLASSES,
            _Path=Path,
            _log=logging.getLogger(__name__),
        )

    async def send(self, msg: Any) -> None:
        "queue a runner message for the job"
        await self.info.send(msg)

    async def fetched(self) -> float:
        "wait until a forecast has been processed; returns the timer delay"
        with anyio.fail_after(5):
            return await self.adm.timer_calls.receive()

    def mins(self, value: float | None = None) -> list[tuple[Path, float]]:
        "expected writes"
        t = self.temps
        return [(DST / n, value if value is not None else min(t[:n])) for n in HORIZONS]


@pytest.mark.anyio
async def test_key_path(monkeypatch):
    "a key path is watched; the forecast is fetched once it's there, then on each timer"
    j = Job(monkeypatch, KEY)
    async with anyio.create_task_group() as tg:
        tg.start_soon(j.run)
        await j.send(_CLASSES.ReadyMsg(0))  # the runner starts with this
        await anyio.wait_all_tasks_blocked()
        key_cls = j.adm.watches[KEY]

        await j.send(_CLASSES.ReadyMsg(1))  # no key yet: nothing happens
        msg = key_cls("KEY")
        msg.value = "KEY"
        await j.send(msg)
        assert await j.fetched() == 600
        assert len(j.calls) == 1
        q = j.calls[0].url.params
        assert (q["appid"], q["lat"], q["units"]) == ("KEY", "49.46", "metric")
        assert j.link.writes == j.mins()
        assert j.adm.done == 1

        await j.send(_CLASSES.TimerMsg(None))  # same forecast: nothing written
        await j.fetched()
        assert len(j.link.writes) == 7

        j.temps[0] = 1.0
        await j.send(_CLASSES.TimerMsg(None))
        await j.fetched()
        assert j.link.writes[7:] == j.mins(1.0)
        assert (len(j.calls), j.adm.done) == (3, 1)
        tg.cancel_scope.cancel()


@pytest.mark.anyio
async def test_key_string(monkeypatch):
    "a string key is used directly"
    j = Job(monkeypatch, "SECRET")
    async with anyio.create_task_group() as tg:
        tg.start_soon(j.run)
        await j.send(_CLASSES.ReadyMsg(0))
        await j.fetched()
        assert j.calls[0].url.params["appid"] == "SECRET"
        assert j.adm.watches == {}
        tg.cancel_scope.cancel()
