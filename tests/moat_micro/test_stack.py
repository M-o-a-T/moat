"""
Test the whole stack
"""

from __future__ import annotations

import anyio
import pytest
from pathlib import Path

from moat.util import yload, yprint, P, ensure_cfg
from moat.micro._test import mpy_stack
from moat.src.test import run
from moat.lib.codec import get_codec

import msgpack

from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    from collections.abc import Awaitable


CFG = """
micro:
  setup:
    args:
      cross: "ext/micropython/mpy-cross/build/mpy-cross"
      config: !P cfg.r
      update: true
      state: std
      large: true
    std: true
    apps:
      r: _test.MpyRaw
    r: &rm
      cwd: /tmp/mpy-test
      mplex: false
      log:
        txt: "M"
    remote: !P r

  # main service. This could be a serial.Link instead, but this way
  # "moat micro setup --run" keeps the existing link going
  run:
    apps:
      r: _test.MpyRaw
      s: remote.Link
      n: net.unix.Port
      co: _test.Cons
    r: *rm
    s:
      path: !P r
      link:
        console: true
        frame: 0xf7
      log:
        txt: "S"
#     log_raw:
#        txt: "SU"
    n: &np
      port: /tmp/moat.test
      log:
        txt: "N"

    co:
      cons: !P s
      prefix: "C"
  cfg:
    r:
      apps:
        c: cfg.Cmd
        r: stdio.StdIO
        f: fs.Cmd
      r:
        link:
          console: true
          frame: 0xf7
        mplex: false
        log:
          txt: "U"
#       log_raw:
#         txt: "RU"
      f:
        root: /tmp/mpy-test

  # Service for connecting to the main code.
  connect:
    remote: !P r.s
    path:
      cfg: !P c
      fs: !P f
    apps:
      r: net.unix.Link
    r: *np

"""


@pytest.mark.anyio()
async def test_stack(tmp_path):
    "full-stack test"
    cfg = yload(CFG, attr=True)
    ensure_cfg("moat.micro", cfg)

    here = Path(".").absolute()
    port = tmp_path / "uport"
    root = tmp_path / "root"
    cfx = tmp_path / "run.cfg"
    cross = here / "ext" / "micropython" / "mpy-cross" / "build" / "mpy-cross"
    cfg.micro.cfg.r.f.root = str(root)
    cfg.micro.run.n.port = str(port)
    cfg.micro.setup.args.cross = str(cross)
    cfg.micro.setup.r.cwd = str(root)
    with cfx.open("w") as f:
        yprint(cfg, f)

    await run("-c", str(cfx), "-VVV", "micro", "setup")
    sc = None

    def rm(s, **kw) -> Awaitable:
        return run("-c", str(cfx), "-VVV", "micro", *s.split(), **kw)

    async with anyio.create_task_group() as tg:

        @tg.start_soon
        async def r_setup():
            nonlocal sc
            with anyio.CancelScope() as sc:
                await run("-c", str(cfx), "-VVV", "micro", "run")

        for _ in range(20):
            await anyio.sleep(0.1)
            if port.exists():
                break
        else:
            raise RuntimeError("Startup failed, no socket")

        async with (
            mpy_stack(tmp_path / "x", cfg.micro.connect) as d,
            d.sub_at(P("r.s")) as s,
            d.cfg_at(P("r.s.c")) as cfg,
        ):
            # First a couple of command tests
            res = await rm("cmd dir_", do_stdout=True)
            assert "\n  c: Cmd\n" in res.stdout
            assert " wr\n" not in res.stdout

            (res,) = await s.cmd("!rdy_")
            assert not res, "Link is not ready"

            res = await rm("cmd f.dir_", do_stdout=True)
            assert "\n- rmdir\n" in res.stdout

            res = await rm("cfg", do_stdout=True)
            assert "\nf:\n  root:" in res.stdout
            assert "fubar" not in res.stdout

            # change some config in remote live data
            res = await rm("cfg -s a.b ~fubar -s a.ft =42", do_stdout=True)
            assert res.stdout == ""

            # change more config but only on local data
            res = await rm("cfg -s a.ft =44 -S", do_stdout=True)
            assert "\n  ft: 44\n" in res.stdout

            # change more config but only on remote data
            res = await rm("cfg -s a.ft =43 -W moat.cf2", do_stdout=True)
            assert res.stdout == ""

            # now do the same thing sanely
            res = await s.cmd("f.dir_")
            assert "rmdir" in res["c"]
            res = await s.f.dir_()
            assert "rmdir" in res["c"]
            cf = await cfg.get()
            assert cf["a"]["b"] == "fubar"
            assert cf["a"]["ft"] == 42

            with (root / "moat.cf2").open("rb") as f:
                cfm = get_codec("cbor").decode(f.read())
            assert cfm["a"]["ft"] == 43
            cfm["a"]["ft"] = 42
            assert cfm == cf

        sc.cancel()
