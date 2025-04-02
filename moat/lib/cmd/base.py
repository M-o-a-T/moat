"""
Base classes for command handlers.
"""

from typing import TYPE_CHECKING
from moat.util import CtxObj
from moat.util.compat import TaskGroup

if TYPE_CHECKING:
    from .msg import Msg
    from moat.util import Path
    from typing import Any,Awaitable,Callable
    Key = str|int|bool

class MsgRemote:
    """
    The "other side" of a message.

    Messages are bidirectional tunnels. The "_send" call on one side
    delivers to the "_recv" method on the other.

    This is the basic no-op implementation which simply forwards data
    from a message to its sibling.
    """
    _remote: MsgRemote = None

    def ml_recv(self, a:list, kw:dict, flags:int) -> None:
        """Message Link Receive

        Called from the other side with whatever data.

        Override this.
        """
        raise NotImplementedError

    def ml_send(self, a:list, kw:dict, flags:int) -> None:
        """Message Link Send

        Forwards some data to the other side.

        Don't override this.
        """
        self._remote.ml_recv(a,kw,flags)

    def set_remote(self, remote:MsgRemote):
        """
        Set (or change) this remote for this one
        """
        if self._remote is not None:
            self._remote.kill()
        self._remote = remote


class Caller(CtxObj):
    """
    Wrapper returned by `MsgSender.cmd`.
    """
    _qlen=0

    def __init__(self, handler:MsgEndpoint, msg:Msg):
        self._msg = msg
        self._handler = handler
        self._dir = SD_NONE
        self._shortcut = shortcut

    def __await__(self):
        "makes this object awaitable"
        return self._call().__await__()

    async def _call(self):
        "helper for __await__ that calls the remote handler"
        res = self._handler.handle(self._msg, self._msg.rcmd)
        await self._msg.result(res)
        return self._msg

    async def _ctx(self):
        if not self._dir:
            self._dir = SD_BOTH
        async with TaskGroup() as tg:
            m1 = self._msg
            m2 = Msg()
            m1.set_remote(m2)
            m2.set_remote(m1)

            # m1 is the one with the command data
            tg.start_soon(self._handler.handle(m1, m1.rcmd))
            m2.prep_stream(self._dir)
            async with m2.stream(self._dir) as m2m:
                yield m2m

    @property
    def stream(self, size:int=42) -> Self:
        """mark as streaming bidirectionally (the default)

        @size: length of the incoming queue
        """
        assert not self._dir
        self._dir = SD_BOTH
        self._qlen = size
        return self

    @property
    def stream_in(self, size:int=42) -> Self:
        """mark as only streaming in.

        @size: length of the incoming queue
        """
        assert not self._dir
        self._dir = SD_IN
        self._qlen = size
        return self

    @property
    def stream_out(self, size:int|None=None) -> Self:
        """mark as only streaming out"""
        assert not self._dir
        self._dir = SD_OUT
        return self

    
class MsgSender:
    """
    Something that accepts and dispatches messages.
    """
    def __init__(self, root:MsgHandler):
        """
        """
        self._root = root

    def cmd(self, cmd:Path, *a:list[Any], **kw:dict[Key,Any]) -> Caller:
        """
        Run a command.

        The result of this call can be used both as an awaitable (straight
        method call) and a context manager (streaming):

        >>> res = await hdl.cmd("foo",42)
        >>> async with hdl.cmd("bar",x=21) as m:
        ...     async for msg, in m:
        ...         m.send(msg*2)

                
        """
        return Caller(self._root, msg.Call(cmd,a,kw))

    def __call__(self, *a:list[Any], **kw:dict[Key,Any]) -> Caller:
        """
        Run a command with an empty path.
        """
        return Caller(self._root, msg.Call((),a,kw))

    def sub_at(self, prefix:Path, may_stream:bool=False) -> MsgSender:
        """
        Returns a SubMsgSender if the path cannot be resolved locally.
        """
        res = self._root.sub_at(prefix, may_stream)
        if isinstance(res,tuple):
            root,rem = res
            if rem:
                return SubMsgSender(root,rem)
            return MsgSender(root)
        return root


class SubMsgSender:
    """
    Something that accepts and dispatches messages and prefixes a subpath.
    """
    def __init__(self, root:MsgHandler, path:Path):
        """
        """
        self._root = root
        self._path 0 path

    def cmd(self, cmd:Path, *a:list[Any], **kw:dict[Key,Any]) -> Caller:
        """
        Run a command.

        The result of this call can be used both as an awaitable (straight
        method call) and a context manager (streaming):

        >>> res = await hdl.cmd("foo",42)
        >>> async with hdl.cmd("bar",x=21) as m:
        ...     async for msg, in m:
        ...         m.send(msg*2)
        """
        return Caller(self._root, msg.Call(self._path+cmd,a,kw))

    def __call__(self, *a:list[Any], **kw:dict[Key,Any]) -> Caller:
        """
        Process a call with an empty path.
        """
        return Caller(self._root, msg.Call(self._path,a,kw))

    def sub_at(self, prefix:Path) -> SubMsgSender:
        """
        Returns a SubMsgSender
        """
        return SubMsgSender(root,self._path+rem)


class MsgEndpoint:
    """
    Something that handles messages.

    Implement ``call(self, *a, *kw)`` and/or ``call_NAME(self, *a, *kw)``
    for simple method calls.

    Implement ``stream(self, *a, *kw)`` and/or ``stream_NAME(self, *a,
    *kw)`` for streamed calls.

    Set ``doc`` or ``doc_NAME`` for call documentation strings.
    """
    async def handle(self, msg:Msg, rcmd:list):
        """
        Process the message.
        """
        if not rcmd:
            if not msg.can_stream and (cmd := getattr(self,"cmd",None)) is not None:
                return await msg.call_simple(cmd)
            else:
                return await msg.call_stream(self.stream)

        if len(rcmd) <= 2 and rcmd[0] == "doc_":
            if msg.a or msg.kw:
                raise TypeError("doc")
            if (doc := getattr(self, f"doc_{rcmd[1]}" if len(rcmd) > 1 else "doc", None)) is not None:
                return await msg.result(self.doc)

        if len(rcmd) == 1:
            if not msg.can_stream and (cmd := getattr(self,f"cmd_{rcmd[0]}",None)) is not None:
                return await msg.call_simple(cmd)
            if (cmd := getattr(self,f"stream_{rcmd[0]}",None)) is not None:
                return await msg.call_stream(cmd)

        # Neither of the above. Find a subcommand.
        scmd = rcmd.pop()
        if (sub := getattr(self,f"sub_{scmd}",None)) is not None:
            return await sub.handle(msg,rcmd)

        raise KeyError(scmd)

    def sub_at(self, path, may_stream:bool=False) -> tuple[MsgEndpoint,Path]|Callable:
        """TODO"""
        return self,path
