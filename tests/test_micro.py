"""
Basic test using a MicroPython subtask
"""
import pytest
from moat.util import NotGiven, as_proxy, attrdict, to_attrdict

from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

CFG="""
apps:
  r: _test.MpyCmd
  a: _test.Cmd
  l: _test.Loop
  _sys: _sys.Cmd
l:
  loop:
    qlen: 2
  link: {}
  log:
    txt: "LOOP"
r:
  mplex: true
  cfg:
    apps:
#     w: wdt.Cmd
      r: stdio.StdIO
      b: _test.Cmd
      c: cfg.Cmd
      _sys: _sys.Cmd
    r:
      link: &link
        lossy: false
        guarded: false
      log:
        txt: "MH"
#     log_raw:
#       txt: "ML"
#     log_rel:
#       txt: "MR"
    tt:
      a: b
      c: [1,2,3]
      x: y
      z: 99

  link: *link
  log:
    txt: "TH"
# log_rel:
#   txt: "TR"

"""

async def test_ping(tmp_path):
    "basic connectivity test"
    async with mpy_stack(tmp_path, CFG) as d:
        res = await d.send("r","b","echo", m="hello")
        assert res == dict(r="hello")


@pytest.mark.parametrize("lossy", [False, True])
@pytest.mark.parametrize("guarded", [False, True])
async def test_modes(tmp_path, lossy, guarded):
    "test different link modes"
    cfu = dict(r=dict(link=dict(lossy=lossy, guarded=guarded),
        cfg=dict(r=dict(link=dict(lossy=lossy, guarded=guarded)))))
    async with mpy_stack(tmp_path, CFG, cfu) as d:
        res = await d.send("r","b","echo", m="hi")
        assert res == {"r":"hi"}


async def test_cfg(tmp_path):
    "test config updating"
    async with mpy_stack(tmp_path, CFG) as d, d.cfg_at("r", "c") as cfg:
        cf = to_attrdict(await cfg.get())
        assert cf.tt.a == "b"
        cf.tt.a = "x"
        assert cf.tt.c[1] == 2
        assert cf.tt.z == 99

        await cfg.set({"tt": {"a": "d", "e": {"f": 42}, "z":NotGiven}})

        cf = to_attrdict(await cfg.get(again=True))
        assert cf.tt.a == "d"
        assert cf.tt.e.f == 42
        assert cf.tt.x == "y"
        assert "z" not in cf.tt


class Bar:
    "proxied test object"

    def __init__(self, x):
        self.x = x

    def __repr__(self):
        return f"{self.__class__.__name__}.x={self.x}"

    def __eq__(self, other):
        return self.x == other.x

@as_proxy("fu")
class Foo(Bar):
    "proxied test class"
    pass  # pylint:disable=unnecessary-pass


LCFG="""
apps:
  a: _test.Cmd
  l: _test.Loop
  _sys: _sys.Cmd
l:
  loop:
    qlen: 2
  link:
    pack: {}
  log:
    txt: "LOOP"
"""
@pytest.mark.parametrize("cons", [None, False, True])
async def test_eval(tmp_path, cons):
    "test proxying"
    cf2 = {} if cons is None else {"l":{"link":{"cons": cons}}}
    async with mpy_stack(tmp_path,LCFG, cf2) as d, d.sub_at("l","_sys","eval") as req:
        from pprint import pprint
        dr=await d.send("l","dir")
        pprint(dr)
        dr=await d.send("l","_sys","dir")
        pprint(dr)

        f = Foo(42)
        b = Bar(95)
        as_proxy("b", b, replace=True)

        await req(x=f,a=["foo"])
        await req(x=42,a=["foo","x"])
        r = await req(x="foo")
        assert isinstance(r,Foo), r
        r = await req(x=f, p=("x",))
        assert r == 42, r

        r = await req(x=b)
        assert r is b, r
        r = await req(x=b, p=("x",))
        assert r == 95, r
        await req(x=b, a=("b",))
        r = await req(x="b.__dict__")
        assert r == {"x":95}, r


async def test_msgpack(tmp_path):
    "test proxying"
    async with mpy_stack(tmp_path,CFG) as d, d.sub_at("r","_sys","eval") as req:
        from pprint import pprint
        dr=await d.send("r","dir")
        pprint(dr)
        dr=await d.send("r","_sys","dir")
        pprint(dr)

        f = Foo(42)
        b = Bar(95)
        as_proxy("b", b, replace=True)

        r = await req(x=f)
        assert isinstance(r,Foo), r
        r = await req(x=f, p=("x",))
        assert r == 42, r

        r = await req(x=b)
        assert r is b
