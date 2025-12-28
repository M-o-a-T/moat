"""
Logging support for stream stacks.
"""

from __future__ import annotations

from moat.lib.micro import log
from moat.lib.rpc import B_FLAGSTR, wire2i_f

from .base import StackedBlk, StackedBuf, StackedMsg


class LogMsg(StackedMsg, StackedBuf, StackedBlk):
    """
    Log whatever messages cross this stack.

    This class implements all of StackedMsg/Buf/Blk.
    """

    # StackedMsg is first because MicroPython uses only the first class and
    # we get `cwr` and `crd` that way.

    def __init__(self, link, cfg):
        super().__init__(link, cfg)
        self.txt = cfg.get("txt", "S")

    async def setup(self):  # noqa:D102
        log("X:%s start", self.txt)
        await super().setup()

    async def teardown(self):  # noqa:D102
        log("X:%s stop", self.txt)
        await super().teardown()

    def _repr(self, m, sub=None):
        if not isinstance(m, dict):
            return repr(m)
        res = []
        for k, v in m.items():
            if sub == k:
                res.append(f"{k}={self._repr(v)}")
            else:
                res.append(f"{k}={v!r}")
        return "{" + " ".join(res) + "}"

    def _repr_bang(self, m):
        m = m[:]
        i, fl = wire2i_f(m.pop(0))
        f = B_FLAGSTR[fl]
        if i >= 0:
            f += "+"
        f += str(i)
        return f, self._repr(m)

    async def send(self, m):  # noqa:D102
        if self.txt[0] == "!" and isinstance(m, (list, tuple)) and m and isinstance(m[0], int):
            log("S:%s %s %s", self.txt[1:], *self._repr_bang(m))
        else:
            log("S:%s %s", self.txt, self._repr(m, "d"))
        try:
            res = await self.s.send(m)
        except BaseException as exc:
            log("S:%s stop %r", self.txt, exc)
            raise
        else:
            log("S:%s =%s", self.txt, self._repr(res, "d"))
            return res

    async def recv(self):  # noqa:D102
        log("R:%s", self.txt)
        try:
            msg = await self.s.recv()
        except BaseException as exc:
            log("R:%s stop %r", self.txt, exc)
            raise
        else:
            if (
                self.txt[0] == "!"
                and isinstance(msg, (list, tuple))
                and msg
                and isinstance(msg[0], int)
            ):
                log("R:%s %s %s", self.txt[1:], *self._repr_bang(msg))
            else:
                log("R:%s %s", self.txt, self._repr(msg, "d"))
            return msg

    async def snd(self, m):  # noqa:D102
        log("SB:%s %r", self.txt, repr_b(m))
        try:
            return await self.s.snd(m)
        except BaseException as exc:
            log("SB:%s stop %r", self.txt, exc)
            raise

    async def rcv(self):  # noqa:D102
        log("RB:%s", self.txt)
        try:
            msg = await self.s.rcv()
        except BaseException as exc:
            log("RB:%s stop %r", self.txt, exc)
            raise
        else:
            log("RB:%s %r", self.txt, repr_b(msg))
            return msg

    async def wr(self, buf):  # noqa:D102
        log("S:%s %r", self.txt, repr_b(buf))
        try:
            res = await self.s.wr(buf)
        except BaseException as exc:
            log("S:%s stop %r", self.txt, exc)
            raise
        else:
            log("S:%s =%r", self.txt, res)
            return res

    async def rd(self, buf) -> len:  # noqa:D102
        log("R:%s %d", self.txt, len(buf))
        try:
            res = await self.s.rd(buf)
        except BaseException as exc:
            log("R:%s stop %r", self.txt, exc)
            raise
        else:
            log("R:%s %r", self.txt, repr_b(buf[:res]))
            return res

    async def cwr(self, buf):  # noqa:D102
        log("SC:%s %r", self.txt, repr_b(buf))
        try:
            res = await self.s.cwr(buf)
        except BaseException as exc:
            log("SC:%s stop %r", self.txt, exc)
            raise
        else:
            log("SC:%s =%r", self.txt, res)
            return res

    async def crd(self, buf) -> len:  # noqa:D102
        log("RC:%s %d", self.txt, len(buf))
        try:
            res = await self.s.crd(buf)
        except BaseException as exc:
            log("RC:%s stop %r", self.txt, exc)
            raise
        else:
            log("RC:%s %r", self.txt, repr_b(buf[:res]))
            return res


def repr_b(b):
    "show bytearray and memoryview as bytes"
    if isinstance(b, bytes):
        return b
    return bytes(b)


LogBuf = LogMsg
LogBlk = LogMsg
