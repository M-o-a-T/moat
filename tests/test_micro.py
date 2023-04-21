"""
Basic test using a MicroPython subtask
"""
import pytest
from moat.util import as_proxy, attrdict, to_attrdict  # pylint:disable=no-name-in-module

from moat.micro._test import mpy_client, mpy_server

pytestmark = pytest.mark.anyio


async def test_ping(tmp_path):
    "basic connectivity test"
    async with mpy_server(tmp_path) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"


@pytest.mark.parametrize("lossy", [False, True])
@pytest.mark.parametrize("guarded", [False, True])
async def test_modes(tmp_path, lossy, guarded):
    "test different link modes"
    async with mpy_server(tmp_path, lossy=lossy, guarded=guarded) as obj:
        async with mpy_client(obj) as req:
            res = await req.send("ping", "hello")
            assert res == "R:hello"


async def test_cfg(tmp_path):
    "test config updating"
    async with mpy_server(tmp_path) as obj:
        assert obj.server.cfg.tt.a == "b"
        obj.server.cfg.tt.a = "x"

        async with mpy_client(obj) as req:
            cfg = to_attrdict(await req.get_cfg())
            assert cfg.tt.a == "b"
            assert cfg.tt.c[1] == 2

            await req.set_cfg({"tt": {"a": "d", "e": {"f": 42}}})

        async with mpy_client(obj) as req:
            cfg = to_attrdict(await req.get_cfg())
            assert cfg.tt.a == "d"
            assert cfg.tt.e.f == 42
            assert cfg.tt.x == "y"


class Bar:
    "proxied test object"

    def __init__(self, x):
        self.x = x

    def __repr__(self):
        return f"{self.__class__.__name__}.x={self.x}"

    def __eq__(self, other):
        return self.x == other.x


@as_proxy("fu", replace=True)
class Foo(Bar):
    "proxied test class"
    pass  # pylint:disable=unnecessary-pass


_val = [
    Foo(42),
    attrdict(x=1, y=2),
]


async def test_msgpack(tmp_path):
    "test proxying"
    async with mpy_server(tmp_path) as obj:
        async with mpy_client(obj) as req:
            f = Foo(42)
            b = Bar(95)
            as_proxy("b", b, replace=True)

            r = await req.send(["sys", "eval"], val=f)
            assert r[0] == f
            assert r[1] == "Foo.x=42"
            r = await req.send(["sys", "eval"], val=f, attrs=("x",))
            assert r[0] == 42, r

            r = await req.send(["sys", "eval"], val=b)
            assert r[0] == b
            assert r[1] == "Bar.x=95"
            r = await req.send(["sys", "eval"], val=b, attrs=("x",))
            assert r[0] == 95, r
