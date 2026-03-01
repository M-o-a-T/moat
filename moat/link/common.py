"""
Common parts
"""

from __future__ import annotations

import anyio

from moat.lib.micro import AC_use
from moat.lib.path import P
from moat.lib.rpc import MsgHandler

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import Msg

    from collections.abc import Callable


class NotAuthorized(RuntimeError):  # noqa: D101
    pass


class _Sub_i(MsgHandler):
    """
    Namespace for internal ``i.*`` commands.
    """

    def __init__(self, parent: CmdCommon):
        super().__init__(parent.cfg)

    doc_ping = dict(_d="Ping, echo", _r="Any: sends all args and keys back")
    doc_乒 = doc_ping  # noqa:PLC2401

    async def stream_ping(self, msg: Msg) -> bool | None:
        """
        This handler replies with "pong" and its arguments, for basic
        round-trip tests.

        乒 ⇒ 乓

        Yes, this name is silly.
        """
        await msg.result("乓", *msg.args, **msg.kw)

    stream_乒 = stream_ping  # noqa:PLC2401

    doc_count = dict(
        _d="count", _o="int:numbers", s="int:start", d="int:delta", e="int:end", t="float:interval"
    )

    async def stream_count(self, msg: Msg) -> bool | None:
        """
        This handler replies with a stream of numbers.

        The result is the first value that crossed the line.
        """
        s = msg.get("s", 0)
        e = msg.get("e", None)
        d = msg.get("d", None)
        t = msg.get("t", 1)

        async with msg.stream_out():
            if e is not None and e < s:
                if d is None:
                    d = -1
                while e < s:
                    await msg.send(s)
                    s += d
                    await anyio.sleep(t)
            else:
                if d is None:
                    d = 1
                while e is None or e > s:
                    await msg.send(s)
                    s += d
                    await anyio.sleep(t)
            await msg.result(s)

    doc_sink = dict(_d="count up", _i="Any:whatever", n="int:accept this many")

    async def stream_sink(self, msg: Msg) -> bool | None:
        """
        This handler swallows an input stream.

        @n is the number of messages that shall be accepted.

        The result is the numebr of messages that arrived.
        """
        n = msg.get("n", -1)
        c = 0

        async with msg.stream_in() as st:
            while True:
                if c == n:
                    break
                _m = await anext(st)

            await msg.result(c)

    doc_echo = dict(_d="count up", _i="Any:whatever", _o="Any:whatever", n="int:accept this many")

    async def stream_echo(self, msg: Msg) -> bool | None:
        """
        This handler echoes an input stream.

        @n is the number of messages that shall be accepted.

        The result is the number of messages that arrived.
        """
        n = msg.get("n", -1)
        c = 0

        async with msg.stream() as st:
            while True:
                if c == n:
                    break
                m = await anext(st)
                await msg.send(m)

            await msg.result(c)


class CmdCommon(MsgHandler):
    """
    Commands every handler should know.

    This includes the 'i' subcommand.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self._sub_i = _Sub_i(self)

    async def setup(self):
        "Attach delegated command handlers."
        await super().setup()
        await AC_use(self, self.delegate(P("i"), self._sub_i))

    doc_i = dict(_d="Internal commands")

    def find_sub(self, scmd: PathElem) -> MsgHandler | Callable | None:
        """
        Resolve subcommands, with a fallback for ``i`` when setup wasn't run.
        """
        if scmd == "i" and "sub_i" not in self.__dict__:
            return self._sub_i
        return super().find_sub(scmd)
