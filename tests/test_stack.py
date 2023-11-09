"""
Test the whole stack
"""
from __future__ import annotations

import pytest
import anyio
from functools import partial

import msgpack

from moat.micro._test import mpy_stack
from moat.src.test import run
from moat.util import yload, yprint
from pathlib import Path

CFG = """
micro:
  setup:
    args:
      cross: "/src/moat/micro/lib/micropython/mpy-cross/build/mpy-cross"
      config: !P cfg.r
      update: true
      state: std
    std: true
    apps:
      r: _test.MpyRaw
    r: &rm
      cwd: /tmp/mpy-test
      mplex: false
      log:
        txt: "M"
    
  # main service. This could be a serial.Link instead, but this way
  # "moat micro setup --run" keeps the existing link going
  apps:
    r: _test.MpyRaw
    s: remote.Link
    n: net.unix.Port
  r: *rm
  s:
    path: !P r
    log:
      txt: "S"
  n: &np
    port: /tmp/moat.test
    log:
      txt: "N"
      
  cfg:
    r:
      apps:
        c: cfg.Cmd
        r: stdio.StdIO
        f: fs.Cmd
      r: *rm
      f:
        root: /tmp/mpy-test

  # Service for connecting to the main code.
  connect:
    apps:
      r: net.unix.Link
    r: *np

logging:
  version: 1
  loggers:
    asyncserf:
      level: INFO
    xknx.raw_socket:
      level: INFO
    moat.micro.direct:
      level: DEBUG
    moat.micro.path:
      level: INFO
  root:
    handlers:
      - stderr
    level: INFO
  handlers:
    logfile:
      class: logging.FileHandler
      filename: test.log
      level: DEBUG
      formatter: std
    stderr:
      class: logging.StreamHandler
      level: DEBUG
      formatter: std
      stream: "ext://sys.stderr"
  formatters:
    std:
      class: "moat.util.TimeOnlyFormatter"
      format: "%(asctime)s %(levelname)s:%(name)s:%(message)s"
      disable_existing_loggers: false
  
"""

@pytest.mark.anyio()
async def test_stack(tmp_path):
    "full-stack test"
    cfg = yload(CFG, attr=True)
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

    rm = partial(run, "-c",str(cfx),"-vvvvv", "micro")
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
        res = await rm("cmd","dir", do_stdout=True)
        assert "\n- s\n" in res.stdout
        assert "\n- dir\n" in res.stdout
        assert "\n- wr\n" not in res.stdout

        res = await rm("cmd","s.f.dir", do_stdout=True)
        assert "\n- rmdir\n" in res.stdout

        res = await rm("-L","r.s","cfg", do_stdout=True)
        assert "\nf:\n  root:" in res.stdout
        assert "fubar" not in res.stdout

        res = await rm("-L","r.s","cfg","-v","a.b","fubar","-e","a.ft","42", do_stdout=True)
        assert res.stdout == ""

        res = await rm("-L","r.s","cfg","-e","a.ft","43", "-W","moat.cf2", do_stdout=True)
        assert res.stdout == ""

        # now do the same thing sanely
        async with mpy_stack(tmp_path/"x", cfg.micro.connect) as d, d.sub_at("r","s") as s,\
                d.cfg_at("r", "s", "c") as cfg:
            res = await s("f","dir")
            assert "rmdir" in res["c"]
            res = await s.f("dir")
            assert "rmdir" in res["c"]
            cf = await cfg.get()
            assert cf["a"]["b"] == "fubar"
            assert cf["a"]["ft"] == 42

            with (root/"moat.cf2").open("rb") as f:
                cfm = msgpack.unpack(f)
                assert cfm["a"]["ft"] == 43
                cfm["a"]["ft"] = 42
                assert cfm == cf

        sc.cancel()

