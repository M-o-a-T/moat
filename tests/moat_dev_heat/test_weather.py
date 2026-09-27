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
from moat.lib.path import P
from moat.link.code.run import Code

from typing import Any

CODE = FSPath(__file__).parents[2] / "examples" / "moat-dev-heat" / "code.weather.min-temp.yaml"
DST = P("test.temp.min.forecast")


class _Link:
    "records writes; holds the API key"

    def __init__(self) -> None:
        self.writes: list[tuple[Any, Any]] = []

    async def d_get(self, path):
        assert path == P("test.weather.key")
        return "KEY"

    async def d_set(self, path, value):
        self.writes.append((path, value))


class _Self:
    "the job runner's call admin"

    def __init__(self) -> None:
        self.done = 0

    async def setup_done(self) -> None:
        self.done += 1


@pytest.mark.anyio
async def test_min_temp(monkeypatch):
    "the minimum over each horizon is written, and only when it changes"
    temps = [5.0, 4.0, 6.0, 3.5, 7.0, 8.0, 2.0] + [9.0] * 20
    calls: list[httpx.Request] = []
    done = anyio.Event()

    def handler(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        if len(calls) == 3:
            # the third forecast lowers every horizon's minimum
            temps[0] = 1.0
        elif len(calls) == 4:  # the third forecast has been processed
            done.set()
        return httpx.Response(200, json={"hourly": [{"temp": t} for t in temps]})

    monkeypatch.setattr(
        httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler))
    )
    link, adm = _Link(), _Self()
    code = Code(link, P("weather.min-temp"))
    code.update(yload(CODE.read_text()), compile=True)

    async with anyio.create_task_group() as tg:
        tg.start_soon(
            partial(
                code,
                key=P("test.weather.key"),
                lat=49.46,
                lon=11.11,
                dst=DST,
                interval=0.01,
                _link=link,
                _self=adm,
                _log=logging.getLogger(__name__),
            )
        )
        with anyio.fail_after(5):
            await done.wait()
        tg.cancel_scope.cancel()

    q = calls[0].url.params
    assert (q["appid"], q["lat"], q["units"]) == ("KEY", "49.46", "metric")
    assert link.writes[:7] == [
        (DST / 4, 3.5),
        (DST / 5, 3.5),
        (DST / 6, 3.5),
        (DST / 10, 2.0),
        (DST / 12, 2.0),
        (DST / 18, 2.0),
        (DST / 24, 2.0),
    ]
    assert link.writes[7:] == [(DST / n, 1.0) for n in (4, 5, 6, 10, 12, 18, 24)]
    assert adm.done == 1
