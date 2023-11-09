"""
Test the whole stack
"""
from __future__ import annotations

import pytest
import anyio

from moat.micro._test import mpy_stack
from moat.src.test import run
from moat.util import yload, yprint
from pathlib import Path

@pytest.mark.anyio()
async def test_stack(tmp_path):
    "full-stack test"
    with open("tests/test_stack.cfg","r") as f:
        cfg = yload(f, attr=True)
    here = Path(".").absolute()
    port = tmp_path/"uport"
    root = tmp_path/"root"
    cfx = tmp_path/"run.cfg"
    cross = here/"lib"/"micropython"/"mpy-cross"/"build"/"mpy-cross"
    cfg.micro.cfg.r.f.root = str(root)
    cfg.micro.n.port = str(port)
    cfg.micro.setup.args.cross = str(cross)
    cfg.micro.setup.r.cwd = str(root)
    with cfx.open("w") as f:
        yprint(cfg, f)

    await run("-c",str(cfx),"-vvvvv", "micro","setup")
    sc = None

    async with anyio.create_task_group() as tg:
        @tg.start_soon
        async def r_setup():
            nonlocal sc
            with anyio.CancelScope() as sc:
                await run("-c",str(cfx),"-vvvvv", "micro","run")
        for _ in range(20):
            await anyio.sleep(0.1)
            if port.exists():
                break
        else:
            raise RuntimeError("Startup failed, no socket")

        # A couple of command tests
        res = await run("-c",str(cfx),"-vvvvv", "micro","cmd","dir", do_stdout=True)
        assert "\n- s\n" in res.stdout
        assert "\n- dir\n" in res.stdout
        assert "\n- wr\n" not in res.stdout

        res = await run("-c",str(cfx),"-vvvvv", "micro","cmd","s.f.dir", do_stdout=True)
        assert "\n- rmdir\n" in res.stdout

        # now do the same thing sanely
        async with mpy_stack(tmp_path/"x", cfg.micro.connect) as d, d.sub_at("r","s") as s:
            res = await s("f","dir")
            assert "rmdir" in res["c"]
            res = await s.f("dir")
            assert "rmdir" in res["c"]
        sc.cancel()

