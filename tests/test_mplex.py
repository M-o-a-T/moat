"""
Empty test file
"""

import sys
import pytest

from moat.micro._test import mpy_stack

CFG="""
apps:
  r: _test.MpyCmd
  a: _test.Cmd
r:
  cfg:
    apps:
#     w: wdt.Cmd
      r: stdio.StdIO
      b: _test.Cmd
    r:
      link: &link
        lossy: False
        guarded: False
      log:
        txt: "MH"
      log_raw:
        txt: "ML"

  link: *link
  log:
    txt: "TH"
  log_raw:
    txt: "TL"
"""
@pytest.mark.anyio
async def test_mplex(tmp_path):
    """
    Basic multiplex test
    """
    async with mpy_stack(tmp_path, CFG) as d:
        r = await d.send("r","b","echo",m="Hi")
        assert r["r"] == "Hi"
        r = await d.send("r","b","echo",m="Ho")
        assert r["r"] == "Ho"

