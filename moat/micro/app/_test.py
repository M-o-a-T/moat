"""
Apps used for testing.
"""

from __future__ import annotations

from moat.micro._test import Loopback, MpyBuf
from moat.micro.compat import AC_use
from moat.micro.proto.stream import MsgpackMsgBlk

from ._test_ import Cmd, Cons  # noqa:F401 pylint:disable=unused-import


def MpyCmd(*a,**k):
    """MoaT link to a local micropython process"""
    from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg
    from moat.micro.stacks.console import console_stack
    class _MpyCmd(BaseCmdMsg):

        async def stream(self):
            mpy = MpyBuf(self.cfg)
            return await AC_use(self, console_stack(mpy, self.cfg))
    return _MpyCmd(*a,**k)


def MpyRaw(*a,**k):
    """stdio of a local micropython process"""
    from moat.micro.cmd.stream.cmdbbm import BaseCmdBBM
    class _MpyRaw(BaseCmdBBM):

        async def stream(self):
            return await AC_use(self, MpyBuf(self.cfg))
    return _MpyRaw(*a,**k)


def Loop(*a,**k):
    """Loopback. Unlike remote.Fwd this goes through msgpack."""
    from moat.micro.cmd.stream.cmdmsg import BaseCmdMsg
    from moat.micro.stacks.console import console_stack
    class _Loop(BaseCmdMsg):

        async def stream(self):
            s = Loopback(**self.cfg.get("loop", {}))
            s.link(s)
            if (li := self.cfg.get("link", None)) is not None:
                if "pack" in li and len(li) == 1:
                    s = await AC_use(self, MsgpackMsgBlk(s, li))
                else:
                    s = await AC_use(self, console_stack(s, self.cfg))
            return s
    return _Loop(*a,**k)
