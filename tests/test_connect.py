"""
Connection tests
"""
import pytest

import os

from moat.util import NotGiven, as_proxy, attrdict, to_attrdict
from moat.micro.compat import log, sleep_ms

from moat.micro._test import mpy_stack

pytestmark = pytest.mark.anyio

# step 1, locally

CFG1="""
apps:
# l: net.unix.Link
# r: net.unix.Port
  a: _test.Cmd
  c: cfg.Cmd
#l:
#  port: /tmp/test.sock
#r:
#  port: /tmp/test.sock
"""


@pytest.mark.parametrize("server_first", [True, False])
@pytest.mark.parametrize("link_in", [True, False])
@pytest.mark.parametrize("unix", [False,True])
async def test_net(tmp_path, server_first, link_in, unix):
    "basic connectivity test"
    if unix:
        sock=tmp_path/"test.sock"
        try:
            sock.unlink()
        except FileNotFoundError:
            pass
    else:
        port=50000+os.getpid()%10000

    async def set_server(c):
        if unix:
            await c.set({
                "apps": {"r": "net.unix.LinkIn" if link_in else "net.unix.Port"},
                "r": {"port": str(sock), "wait":False},
                }, sync=True)
        else:
            await c.set({
                "apps": {"r": "net.tcp.LinkIn" if link_in else "net.tcp.Port"},
                "r": {"host": "127.0.0.1", "port": port, "wait":False},
                }, sync=True)

    async def set_client(c):
        await c.set({
#           "apps": {"l": "net.unix.Link"},
#           "l": {"port": str(sock)},
            "apps": {"l": "sub.Err"},
            "l": {
                "app":"net.unix.Link" if unix else "net.tcp.Link",
                "cfg":{"port": str(sock)} if unix else {"host":"127.0.0.1","port":port},
                "retry":9,
                "timeout":100,
                "wait": False,
              },
            }, sync=True)

    async with mpy_stack(tmp_path, CFG1) as d, d.cfg_at("c") as c:
        await (set_server if server_first else set_client)(c)
        await sleep_ms(100)
        await (set_client if server_first else set_server)(c)

        res = await d.send("l","a","echo", m="hello")
        assert res == dict(r="hello")



#
#
#CFG="""
#apps:
#  r: _test.MpyCmd
#  a: _test.Cmd
#  l: _test.Loop
#  _sys: _sys.Cmd
#l:
#  loop:
#    qlen: 2
#  link: {}
#  log:
#    txt: "LOOP"
#r:
#  cfg:
#    apps:
##     w: wdt.Cmd
#      r: stdio.StdIO
#      b: _test.Cmd
#      c: cfg.Cmd
#      _sys: _sys.Cmd
#    r:
#      link: &link
#        lossy: false
#        guarded: false
#      log:
#        txt: "MH"
##     log_raw:
##       txt: "ML"
##     log_rel:
##       txt: "MR"
#    tt:
#      a: b
#      c: [1,2,3]
#      x: y
#      z: 99
#
#  link: *link
#  log:
#    txt: "TH"
## log_rel:
##   txt: "TR"
#
#"""
#
#
#@pytest.mark.parametrize("lossy", [False, True])
#@pytest.mark.parametrize("guarded", [False, True])
#async def test_modes(tmp_path, lossy, guarded):
#    "test different link modes"
#    cfu = dict(r=dict(link=dict(lossy=lossy, guarded=guarded),
#        cfg=dict(r=dict(link=dict(lossy=lossy, guarded=guarded)))))
#    async with mpy_stack(tmp_path, CFG, cfu) as d:
#        res = await d.send("r","b","echo", m="hi")
#        assert res == {"r":"hi"}
#
#
#async def test_cfg(tmp_path):
#    "test config updating"
#    async with mpy_stack(tmp_path, CFG) as d, d.cfg_at("r", "c") as cfg:
#        cf = to_attrdict(await cfg.get())
#        assert cf.tt.a == "b"
#        cf.tt.a = "x"
#        assert cf.tt.c[1] == 2
#        assert cf.tt.z == 99
#
#        await cfg.set({"tt": {"a": "d", "e": {"f": 42}, "z":NotGiven}})
#
#        cf = to_attrdict(await cfg.get(again=True))
#        assert cf.tt.a == "d"
#        assert cf.tt.e.f == 42
#        assert cf.tt.x == "y"
#        assert "z" not in cf.tt
#
#
#class Bar:
#    "proxied test object"
#
#    def __init__(self, x):
#        self.x = x
#
#    def __repr__(self):
#        return f"{self.__class__.__name__}.x={self.x}"
#
#    def __eq__(self, other):
#        return self.x == other.x
#
#@as_proxy("fu")
#class Foo(Bar):
#    "proxied test class"
#    pass  # pylint:disable=unnecessary-pass
#
#
#LCFG="""
#apps:
#  a: _test.Cmd
#  l: _test.Loop
#  _sys: _sys.Cmd
#l:
#  loop:
#    qlen: 2
#  link:
#    pack: {}
#  log:
#    txt: "LOOP"
#"""
#@pytest.mark.parametrize("cons", [None, False, True])
#async def test_eval(tmp_path, cons):
#    "test proxying"
#    cf2 = {} if cons is None else {"l":{"link":{"cons": cons}}}
#    async with mpy_stack(tmp_path,LCFG, cf2) as d, d.sub_at("l","_sys","eval") as req:
#        from pprint import pprint
#        dr=await d.send("l","_dir")
#        pprint(dr)
#        dr=await d.send("l","_sys","_dir")
#        pprint(dr)
#
#        f = Foo(42)
#        b = Bar(95)
#        as_proxy("b", b, replace=True)
#
#        await req(x=f,a=["foo"])
#        await req(x=42,a=["foo","x"])
#        r = await req(x="foo")
#        assert isinstance(r,Foo), r
#        r = await req(x=f, p=("x",))
#        assert r == 42, r
#
#        r = await req(x=b)
#        assert r is b, r
#        r = await req(x=b, p=("x",))
#        assert r == 95, r
#        await req(x=b, a=("b",))
#        r = await req(x="b.__dict__")
#        assert r == {"x":95}, r
#
#
#async def test_msgpack(tmp_path):
#    "test proxying"
#    async with mpy_stack(tmp_path,CFG) as d, d.sub_at("r","_sys","eval") as req:
#        from pprint import pprint
#        dr=await d.send("r","_dir")
#        pprint(dr)
#        dr=await d.send("r","_sys","_dir")
#        pprint(dr)
#
#        f = Foo(42)
#        b = Bar(95)
#        as_proxy("b", b, replace=True)
#
#        r = await req(x=f)
#        assert isinstance(r,Foo), r
#        r = await req(x=f, p=("x",))
#        assert r == 42, r
#
#        r = await req(x=b)
#        assert r is b
