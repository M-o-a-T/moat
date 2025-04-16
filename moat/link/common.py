"""
Common parts
"""

from __future__ import annotations

from typing import TYPE_CHECKING
import anyio

from moat.lib.cmd.base import MsgHandler

if TYPE_CHECKING:
    from typing import Awaitable
    from moat.lib.cmd import Msg


class NotAuthorized(RuntimeError):
    pass


class CmdCommon(MsgHandler):
    """
    Commands every handler should know.

    This includes the 'i' subcommand.
    """

    doc_i = dict(_d="Internal commands")

    def sub_i(self, msg: Msg, rcmd: list) -> Awaitable[None]:
        "Local subcommand redirect for 'i'"
        return self.handle(msg, rcmd, "i")

    doc_i_ping = dict(_d="Ping, echo", _r="Any: sends all args and keys back")
    doc_i_乒 = doc_i_ping

    async def stream_i_ping(self, msg: Msg) -> bool | None:
        """
        This handler replies with "pong" and its arguments, for basic
        round-trip tests.

        乒 ⇒ 乓

        Yes, this name is silly.
        """
        await msg.result("乓", *msg.args, **msg.kw)

    stream_i_乒 = stream_i_ping

    doc_i_count = dict(
        _d="count", _o="int:numbers", s="int:start", d="int:delta", e="int:end", t="float:interval"
    )

    async def stream_i_count(self, msg: Msg) -> bool | None:
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

    doc_i_sink = dict(_d="count up", _i="Any:whatever", n="int:accept this many")

    async def stream_i_sink(self, msg: Msg) -> bool | None:
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

    doc_i_echo = dict(
        _d="count up", _i="Any:whatever", _o="Any:whatever", n="int:accept this many"
    )

    async def stream_i_echo(self, msg: Msg) -> bool | None:
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
