# noqa:D100
from __future__ import annotations

import errno
import socket
import sys
import time
from contextlib import asynccontextmanager

import trio

from moat.bus.handler import ERR, BaseHandler

from typing import Any


class Client(BaseHandler):  # noqa:D101
    __socket: str
    __timeout: float
    __timeout2: float
    __dest: int | None
    __msg: Any
    __wire_in: int
    __wire_out: int | None
    __evt: dict[int, Any]
    __c: Any
    __t: float | None
    __v: bool
    __sock: Any
    __q: Any
    __tg: trio.Nursery
    __kick: Any

    def __init__(
        self,
        wires: int,
        timeout: float = 0.01,
        timeout2: float = 0.005,
        socket: str = "/tmp/moatbus",  # noqa:S108
        verbose: bool = False,
        dest: int | None = None,
    ) -> None:
        self.__socket = socket
        self.__timeout = timeout
        self.__timeout2 = timeout2
        self.__dest = dest

        self.__msg = None
        self.__wire_in = 0
        self.__wire_out = None
        self.__evt = {}
        self.__c = None
        self.__t: float | None = None
        self.__v = verbose

        super().__init__(wires=wires)

    async def main(self, *, task_status: Any = trio.TASK_STATUS_IGNORED) -> None:  # noqa:D102
        task_status.started()
        while True:
            if self.__t is not None:
                t1 = time.monotonic()
            if self.__msg is not None:
                m, self.__msg = self.__msg, None
                await self.__q.put(m)
            if self.__wire_out is not None:
                b, self.__wire_out = self.__wire_out, None
                await self.__sock.send(bytes((b,)))

            try:
                b = None
                if self.__t is None:
                    with trio.CancelScope() as c:
                        self.__kick = c
                        b = await self.__sock.receive(1)
                else:
                    with trio.fail_after(max(self.__t / 1000, 0)) as c:
                        self.__kick = c
                        b = await self.__sock.receive(1)
            except trio.BrokenResourceError:
                return
            except (trio.TooSlowError, TimeoutError):
                self.__c = None
                self.__t = None
                self.timeout()
            else:
                self.__c = None
                if b is None:
                    pass
                elif not b:
                    sys.exit(1)
                if self.__t is not None:
                    t2 = time.monotonic()
                    t1, t2 = t2, t2 - t1
                    self.__t -= t2

                if b:
                    self.__wire_in = b[0]
                    self.debug("WIRE %r", b)
                    self.wire(b[0])
                if self.__t is not None and self.__t <= 0:
                    self.__t = None
                    self.timeout()

    async def send(self, msg: Any) -> None:  # ty:ignore[invalid-method-override]
        """Send a message and wait for the result."""
        mi = id(msg)
        if mi in self.__evt:
            raise RuntimeError("Already sending")
        self.__evt[mi] = ev = trio.Event()
        super().send(msg)
        await ev.wait()
        self.__evt.pop(mi)

    def get_wire(self) -> int:  # noqa: D102
        return self.__wire_in

    def set_wire(self, bits: int) -> None:  # noqa: D102
        self.debug("OUT! %s", bits)
        self.__wire_out = bits
        if self.__c is not None:
            self.__c.cancel()

    def transmitted(self, msg: Any, res: Any) -> None:  # noqa: D102
        msg.res = res
        self.debug("SENT %r %s", msg, res)
        mi = id(msg)
        ev = self.__evt.pop(mi)
        self.__evt[mi] = res
        ev.set()

    def process(self, msg: Any) -> bool:  # noqa: D102
        self.debug("RCVD %r", msg)
        if self.__dest is not None and self.__dest == msg.dst:
            self.__msg = msg
            return True
        elif self.__dest is None:
            self.__msg = msg
        return False

    def report_error(self, typ: Any, **kw: Any) -> None:  # noqa: D102
        if kw:
            self.debug("ERROR %s %s", typ, kw, v=True)
        else:
            self.debug("ERROR %s", typ)
        if typ == ERR.COLLISION:
            print("COLL", kw)

    def debug(self, msg: str, *a: Any, v: bool = False) -> None:  # noqa: D102
        if not v and not self.__v:
            return
        if a:
            msg %= a
        print(msg)

    def set_timeout(self, timeout: float) -> None:  # noqa: D102
        t = timeout
        if t < 0:
            self.debug("TIME --")
        elif t == 0:
            self.debug("TIME next")
        else:
            self.debug("TIME %.2f", t)
        if self.__c is not None:
            self.__c.cancel()
        if t < 0:
            self.__t = None
        elif t:
            self.__t = self.__timeout * t
        else:
            self.__t = self.__timeout2

    @asynccontextmanager
    async def run(self) -> Any:  # noqa: D102
        async with trio.open_nursery() as tg:
            with trio.socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                await sock.connect(self.__socket)
                self.__tg = tg
                self.__sock = sock
                self.__q = trio.open_memory_channel(100)[1]

                await tg.start(self.main)
                try:
                    yield self
                except trio.BrokenResourceError:
                    pass
                except OSError as e:
                    if e.errno != errno.EBADF:
                        raise

    def __aiter__(self) -> Client:
        return self

    async def __anext__(self) -> Any:
        return await self.__q.get()
