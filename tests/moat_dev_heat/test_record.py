"""
Tests for the side-car recorder, open-loop replay and the legacy converter.
"""

from __future__ import annotations

import anyio
import io
import pytest
from pathlib import Path as FSPath

from moat.util import NotGiven, yload
from moat.dev.heat.record import (
    HEADER,
    LEGACY_PATHS,
    convert_legacy,
    read_timeline,
    record,
    replay,
)
from moat.lib.path import P

DATA = FSPath(__file__).parent / "data"
REC = P("test.rec")
COPY = P("test.copy")


@pytest.mark.anyio
async def test_round_trip(heat, tmp_path):
    "record the state and changes of a subtree; replay them below another path"
    link = heat.link
    await link.d_set(REC / "a", 1, retain=True)
    await link.d_set(REC / "b", {"x": 2}, retain=True)
    await link.i_sync()

    out = io.StringIO()
    with anyio.CancelScope() as sc:
        async with anyio.create_task_group() as tg:
            await tg.start(record, link, out, [REC])
            await link.d_set(REC / "c", 3, retain=True)
            await link.d_set(REC / "a", NotGiven, retain=True)
            await link.d_set(REC / "b", {"x": 4}, retain=True)
            await link.i_sync()
            await anyio.sleep(0.3)
            sc.cancel()

    docs = [d for d in yload(out.getvalue(), multi=True) if d is not None]
    assert docs[0][HEADER] == 1
    assert docs[0]["paths"] == [REC]
    ev = [(p, v[0] if v else NotGiven) for _t, p, *v in docs[1:]]
    assert ev[:2] == [(REC / "a", 1), (REC / "b", {"x": 2})]  # the initial state
    assert ev[2:] == [(REC / "c", 3), (REC / "a", NotGiven), (REC / "b", {"x": 4})]
    ts = [d[0] for d in docs[1:]]
    assert ts == sorted(ts)

    f = tmp_path / "t.yaml"
    f.write_text(out.getvalue())
    t0 = anyio.current_time()
    n = await replay(link, read_timeline(str(f)), speed=1, prefix=COPY)
    assert n == 5
    assert anyio.current_time() - t0 >= ts[-1] - 0.05  # at the recorded pace
    await link.i_sync()
    assert await link.d_get(COPY + REC / "b") == {"x": 4}
    assert await link.d_get(COPY + REC / "c") == 3
    with pytest.raises(KeyError):
        await link.d_get(COPY + REC / "a")


def test_convert_legacy():
    "a legacy recording becomes a timeline of changed inputs"
    docs = yload((DATA / "legacy_record.yaml").read_text(), multi=True)
    ev = list(convert_legacy(docs))
    tin, tout, tbh = LEGACY_PATHS["t_in"], LEGACY_PATHS["t_out"], LEGACY_PATHS["tb_heat"]
    pw, pred = LEGACY_PATHS["m_power"], LEGACY_PATHS["m_air_pred"]
    assert ev == [
        (0.0, tin, 30.0),
        (0.0, tout, 30.0),
        (0.0, tbh, 40.5),
        (0.0, pw, 0),
        (10.5, tout, 31.5),
        (20.0, tbh, 41.0),
        (20.0, pw, 1.2),
        (20.0, pred, -3.5),
    ]
