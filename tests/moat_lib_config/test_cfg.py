# noqa:D100
from __future__ import annotations

import anyio
import pytest
from pathlib import Path as FSPath

from moat.util import NotGiven, attrdict, yprint
from moat.lib.config import CfgStore, monitor
from moat.lib.path import P


def test_cfg(tmp_path):
    "Test loading a config"
    here = FSPath(__file__).parent
    cfg = CfgStore(here=here, load_all=None, name=None, preload=attrdict(env=NotGiven))
    cfg.add("test_cfg.yaml")
    cfg.mod(P("mod.local.drop"), NotGiven)
    cfg.mod(P("data.pull"), "quux")

    cfg.redo()

    r = cfg.result
    res = tmp_path / "cfg.yaml"
    with res.open("w") as rf:
        yprint(r, rf)
    print("\nResult:")
    yprint(r)
    print()

    assert "logging" not in r
    assert "env" not in r
    assert r.data.foo == "bar"
    assert r.data.baz == "quux"
    assert "override" not in r.mod
    assert "drop" not in r.mod.local


@pytest.mark.anyio
async def test_updated():
    "Test notification of config updates"
    here = FSPath(__file__).parent
    cfg = CfgStore(here=here, load_all=None, name=None, preload=attrdict(env=NotGiven))
    cfg.add("test_cfg.yaml")
    cfg.mod(P("data.pull"), "quux")
    upd = 0
    async with anyio.create_task_group() as tg:

        @tg.start_soon
        async def mon():
            nonlocal upd
            with monitor(cfg.result.mod, delay=0.05) as mon:
                async for _ in mon:
                    upd += 1

        await anyio.sleep(0.01)
        cfg.mod(P("mod.local.drop"), NotGiven)
        cfg.redo()
        await anyio.sleep(0.1)
        assert upd == 1
        cfg.mod(P("mod.local.foo"), "barf")
        assert cfg.result.mod.local.foo == "barf"
        await anyio.sleep(0.1)
        assert upd == 2

        tg.cancel_scope.cancel()
