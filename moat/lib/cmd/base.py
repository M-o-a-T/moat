"""
Base classes for command handlers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING
from moat.util import CtxObj
from moat.util.compat import TaskGroup, QueueFull, log
from .const import *

_link_id = 0

if TYPE_CHECKING:
    from .msg import Msg
    from moat.util import Path
    from typing import Any, Awaitable, Callable

    Key = str | int | bool


class MsgLink:
    """
    The "other side" of a message.

    Message links are bidirectional tunnels. `ml_send` on one side delivers
    to the `ml_recv` method of the other.

    This class is the base implementation, which simply forwards data from
    a message to its sibling.
    """

    _remote: MsgLink = None
    _end: bool = False

    def __init__(self):
        """
        Link setup. By default does nothing.

        You need to call `set_remote` before this is usable.
        """
        global _link_id
        _link_id += 1
        self.link_id = _link_id

    def ml_recv(self, a: list, kw: dict, flags: int) -> None:
        """Message Link Receive

        Called from the other side with whatever data.

        Override this.
        """
        raise NotImplementedError

    def ml_send(self, a: list, kw: dict, flags: int) -> None:
        """Message Link Send

        This method forwards data to the other side.

        Don't override this.
        """
        if self._remote is None:
            log("? No remote %r", self)
        else:
            self._remote.ml_recv(a, kw, flags)
        if not flags & B_STREAM:
            self.set_end()

    @property
    def end_both(self) -> bool:
        if self._remote and not self._remote.end_here:
            return False
        return self._end

    @property
    def end_here(self) -> bool:
        return self._end

    @property
    def end_there(self) -> bool:
        if self._remote is None:
            return True
        return self._remote.end_here

    @property
    def remote(self):
        return self._remote

    def stream_detach(self):
        pass

    def set_end(self):
        log("SET END L%d", self.link_id)
        #       if self._end:  #  or self.link_id in {4,5}:
        #           breakpoint() # dup set end
        self._end = True
        if self.end_both:
            if self._remote:
                self._remote.stream_detach()
            self.stream_detach()

    def set_remote(self, remote: MsgLink):
        """
        Set (or change) my remote for @remote.

        The old remote, if any is `kill`ed.
        """
        if self._remote is not None:
            self._remote.kill()
        self._remote = remote

    def kill(self):
        """
        This link is getting un-linked, thus should free its data.
        """
        self._remote = None

    def __repr__(self):
        return f"<{self.__class__.__name__}:L{self.link_id} r{'=L' + str(self._remote.link_id) if self._remote else '-'}>"


class Caller(CtxObj):
    """
    This is the Wrapper returned by `MsgSender.cmd`.

    You should not instantiate this class directly.
    """

    _qlen = 0

    def __init__(self, handler: MsgHandler, msg: Msg):
        self._msg = msg
        self._handler = handler
        self._dir = SD_NONE

    def __await__(self):
        "makes this object awaitable"
        return self._call().__await__()

    async def _call(self):
        "helper for __await__ that calls the remote handler"
        msg = self._msg
        await self._handler.handle(msg, self._msg.rcmd)
        await msg.wait_replied()
        return msg

    async def _ctx(self):
        if not self._dir:
            self._dir = SD_BOTH
        m1 = self._msg
        async with (
            TaskGroup() as tg,
            m1.ensure_remote() as m2,
        ):
            # m2 is the one with the command data
            tg.start_soon(self._handler.handle, m2, m2.rcmd)
            async with m1.stream_call(self._dir):
                yield m1

    def stream(self, size: int = 42) -> Self:
        """mark as streaming bidirectionally (the default)

        @size: length of the incoming queue
        """
        assert not self._dir
        self._dir = SD_BOTH
        self._qlen = size
        return self

    def stream_in(self, size: int = 42) -> Self:
        """mark as only streaming in.

        @size: length of the incoming queue
        """
        assert not self._dir
        self._dir = SD_IN
        self._qlen = size
        return self

    def stream_out(self, size: int | None = None) -> Self:
        """mark as only streaming out"""
        assert not self._dir
        self._dir = SD_OUT
        return self


class MsgSender:
    """
    Something that accepts and dispatches messages.
    """

    def __init__(self, root: MsgHandler):
        """ """
        self._root = root

    @property
    def root(self):
        return self._root

    def handle(self, msg: Msg, rcmd: list) -> Awaitable[None]:
        return self._root.handle(msg, rcmd)

    def cmd(self, cmd: Path, *a: list[Any], **kw: dict[Key, Any]) -> Caller:
        """
        Run a command.

        The result of this call can be used both as an awaitable (straight
        method call) and a context manager (streaming):

        >>> res = await hdl.cmd("foo",42)
        >>> async with hdl.cmd("bar",x=21) as m:
        ...     async for msg, in m:
        ...         m.send(msg*2)


        """
        from .msg import Msg

        return Caller(self._root, Msg.Call(cmd, a, kw))

    def __call__(self, *a: list[Any], **kw: dict[Key, Any]) -> Caller:
        """
        Run a command with an empty path.
        """
        from .msg import Msg

        return Caller(self._root, Msg.Call((), a, kw))

    def sub_at(self, prefix: Path, may_stream: bool = False) -> MsgSender:
        """
        Returns a SubMsgSender if the path cannot be resolved locally.
        """
        res = self._root.sub_at(prefix, may_stream)
        if isinstance(res, tuple):
            root, rem = res
            if rem:
                return SubMsgSender(root, rem)
            return MsgSender(root)
        return root


class SubMsgSender(MsgSender):
    """
    Something that accepts and dispatches messages and prefixes a subpath.
    """

    def __init__(self, root: MsgHandler, path: Path):
        """
        Setup.
        """
        super().__init__(root)
        self._path = path
        self._rpath = list(path)
        self._rpath.reverse()

    def handle(self, msg: Msg, rcmd: list) -> Awaitable[None]:
        rcmd.append(self._rpath)
        return self._root.handle(msg, rcmd)

    def cmd(self, cmd: Path, *a: list[Any], **kw: dict[Key, Any]) -> Caller:
        """
        Run a command.

        The result of this call can be used both as an awaitable (straight
        method call) and a context manager (streaming):

        >>> res = await hdl.cmd("foo",42)
        >>> async with hdl.cmd("bar",x=21) as m:
        ...     async for msg, in m:
        ...         m.send(msg*2)
        """
        return Caller(self._root, msg.Call(self._path + cmd, a, kw))

    def __call__(self, *a: list[Any], **kw: dict[Key, Any]) -> Caller:
        """
        Process a call with an empty path.
        """
        return Caller(self._root, Msg.Call(self._path, a, kw))

    def sub_at(self, prefix: Path) -> SubMsgSender:
        """
        Returns a SubMsgSender
        """
        return SubMsgSender(root, self._path + rem)


class MsgHandler(CtxObj):
    """
    Something that handles messages.

    Implement ``call(self, *a, *kw)`` and/or ``call_NAME(self, *a, *kw)``
    for simple method calls.

    Implement ``stream(self, *a, *kw)`` and/or ``stream_NAME(self, *a,
    *kw)`` for streamed calls.

    Set ``doc`` or ``doc_NAME`` for call documentation strings.

    This class inherits from CtxObj for compatibility (no multiple
    inheritance in MicroPython) but doesn't itself contain a context
    manager.
    """

    @property
    def root(self):
        return self

    async def handle(self, msg: Msg, rcmd: list, *prefix: list[str]):
        """
        Process the message.
        """
        pref = "_" + "_".join(prefix) if prefix else ""

        # Process direct calls.
        if not rcmd:
            if not msg.can_stream and (cmd := getattr(self, f"cmd{pref}", None)) is not None:
                return await msg.call_simple(cmd)
            else:
                return await msg.call_stream(self.stream)

        # Process requests for documentation.
        if len(rcmd) <= 2 and rcmd[0] == "doc_":
            if msg.a or msg.kw:
                raise TypeError("doc")
            if (
                doc := getattr(
                    self, f"doc{pref}_{rcmd[1]}" if len(rcmd) > 1 else f"doc{pref}", None
                )
            ) is not None:
                return await msg.result(self.doc)

        # Process command handlers of this class.
        if len(rcmd) == 1:
            if (
                not msg.can_stream
                and (cmd := getattr(self, f"cmd{pref}_{rcmd[0]}", None)) is not None
            ):
                return await msg.call_simple(cmd)
            if (cmd := getattr(self, f"stream{pref}_{rcmd[0]}", None)) is not None:
                return await msg.call_stream(cmd)

        # Neither of the above: find a subcommand.
        scmd = rcmd.pop()
        if (sub := getattr(self, f"sub{pref}_{scmd}", None)) is not None:
            return await sub.handle(msg, rcmd)

        raise KeyError(scmd)

    def sub_at(self, path, may_stream: bool = False) -> tuple[MsgHandler, Path] | Callable:
        """TODO"""
        return self, path

    async def _ctx(self):
        raise NotImplementedError
