"""
Base classes for command handlers.
"""

from __future__ import annotations
from functools import partial
from contextlib import asynccontextmanager

from typing import TYPE_CHECKING
from moat.util.compat import TaskGroup, QueueFull, log, print_exc, ACM, AC_exit, shield
from moat.util import Path
from moat.util.exc import ungroup
from .const import *

_link_id = 0

if TYPE_CHECKING:
    from .msg import Msg
    from moat.util import Path
    from typing import Any, Awaitable, Callable, Sequence, Mapping

    Key = str | int | bool
    OptDict = Mapping[str,Any]|None


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

    async def ml_recv(self, a: Sequence, kw: OptDict, flags: int) -> None:
        """Message Link Receive

        Called from the other side with whatever data.

        Override this.
        """
        raise NotImplementedError

    async def ml_send(self, a: Sequence, kw: OptDict, flags: int) -> None:
        """Message Link Send

        This method forwards data to the other side.

        Don't override this.
        """
        if self._remote is None:
            raise EOFError
        try:
            await self._remote.ml_recv(a, kw, flags)
        except BaseException:
            await self.kill()
            raise
        else:
            if not flags & B_STREAM:
                self.set_end()

    async def ml_send_error(self, exc):
        """
        Send an exception.
        """
        if self.end_here:
            log("Err after end: %r", self)
            print_exc(exc)
            return
        try:
            # send the error directly
            await self.ml_send((exc,), None, B_ERROR)
        except Exception as exc:
            try:
                # that failed? send the error name and arguments
                await self.ml_send((exc.__class__.__name__,) + exc.args, None, B_ERROR)
            except Exception:
                try:
                    # that failed too? send just the error name
                    await self.ml_send((exc.__class__.__name__,), None, B_ERROR)
                except Exception:
                    try:
                        # oh well, just send a naked error indication
                        await self.ml_send([E_ERROR], None, B_ERROR)
                    except Exception:
                        # Give up.
                        pass

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
        """
        Called when this stream is done.

        Override this method to clean up any related data.

        This method must be idempotent.
        """
        pass

    def set_end(self):
        "The send side of this stream has ended."
        self._end = True
        if self.end_both:
            if self._remote is not None:
                self._remote.stream_detach()
            self.stream_detach()
            self._remote = None

    async def kill(self):
        """
        No further communication is possible.

        This must only be called if e.g. a link is down.
        It tries to deliver cancel messages to both sides.
        """
        rem = self._remote
        if self._end:
            pass
        else:
            rs = self if rem is None else rem
            rs.set_end()
            try:
                with shield():
                    await rs.ml_recv([E_CANCEL], None, B_ERROR)
            except Exception as exc:
                pass

    def set_remote(self, remote: MsgLink):
        """
        Set (or change) my remote for @remote.

        The old remote, if any, is `kill`ed.
        """
        rem = self._remote
        if rem is not None:
            rem._remote = None
            rem.set_end()
        self._remote = remote

    def __repr__(self):
        return f"<{self.__class__.__name__}:L{self.link_id} r{'=L' + str(self._remote.link_id) if self._remote else '-'}>"


class Caller:
    """
    This is the Wrapper returned by `MsgSender.cmd`.

    You should not instantiate this class directly.
    """

    _qlen = 0

    def __init__(self, handler: MsgHandler, data: tuple[str, list | tuple, dict]):
        self.data = data
        self.handler = handler
        self._dir = SD_NONE

    def __await__(self):
        "makes this object awaitable, CPython"
        return self._call().__await__()

    def __iter__(self):
        "makes this object awaitable, MicroPython"
        # this depends on µPy doing the right thing
        return self._call()

    async def _call(self):
        "helper for __await__ that calls the remote handler"
        from .msg import Msg

        msg = Msg.Call(*self.data)

        await self.handler.handle(msg, msg.rcmd)
        await msg.wait_replied()
        return msg

    async def __aenter__(self):
        acm = ACM(self)
        try:
            if not self._dir:
                self._dir = SD_BOTH

            from .msg import Msg

            m1 = Msg.Call(*self.data)

            tg = await acm(TaskGroup())
            m2 = await acm(m1.ensure_remote())
            # m2 is the one with the command data
            tg.start_soon(self.handler.handle, m2, m2.rcmd)
            await acm(m1._stream_call(self._dir))
            return m1
        except BaseException as exc:
            try:
                await AC_exit(self, type(exc), exc, None)
            except BaseException as ex:
                ex = ungroup.one(ex)
                if ex is not ungroup.one(exc):
                    raise
            raise

    async def __aexit__(self, *err):
        return await AC_exit(self, *err)

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

    def stream_out(self) -> Self:
        """mark as only streaming out"""
        assert not self._dir
        self._dir = SD_OUT
        return self


class BaseMsgHandler:
    """
    Somewhat-abstract superclass for anythiong that accepts messages.
    """

    def handle(self, msg: Msg, rcmd: list) -> Awaitable[None]:
        """
        Handle this message stream.

        @rcmd is the inverted command prefix. Hierarchical handlers chop an
        element off the end.
        """
        raise NotImplementedError


class MsgSender(BaseMsgHandler):
    """
    This class is the client-side API of the MoaT Command multiplexer.
    """

    Caller_ = Caller

    def __init__(self, root: MsgHandler):
        """ """
        self._root = root

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    @property
    def root(self):
        return self._root

    def set_root(self, root):
        if type(self) != MsgSender:
            raise RuntimeError("not in a subclass")
        self._root = root

    def handle(self, msg: Msg, rcmd: list) -> Awaitable[None]:
        """
        Redirect to the underlying command handler.
        """
        return self.root.handle(msg, rcmd)

    def cmd(self, cmd: Path, *a: Any, **kw: Any) -> Caller:
        """
        Run the command at this path.

        The result of this call can be used both as an awaitable (straight
        method call) and a context manager (streaming):

        >>> res = await hdl.cmd("foo",42)
        >>> async with hdl.cmd("bar",x=21) as m:
        ...     async for msg, in m:
        ...         m.send(msg*2)


        """
        return self.Caller_(self, (cmd, a, kw))

    def sub_at(self, prefix: Path, may_stream: bool = False) -> MsgSender:
        """
        Returns a SubMsgSender if the path cannot be resolved locally.
        """
        res = self.root.find_handler(prefix, may_stream)
        if isinstance(res, tuple):
            root, rem = res
            if rem:
                return SubMsgSender(root, rem)
            return MsgSender(root)
        return res

    def __getattr__(self, x):
        """
        Returns a SubMsgSender for this name
        """
        return self.sub_at(Path(x))


class SubMsgSender(MsgSender):
    """
    This `MsgSender` subclass auto-prefixes a path to all calls.
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
        rcmd.extend(self._rpath)
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
        # The path is modified in .handle
        return Caller(self, (cmd, a, kw))

    def stream(self, *a, **kw):
        return self.cmd((), *a, **kw).stream()

    def stream_in(self, *a, **kw):
        return self.cmd((), *a, **kw).stream_in()

    def stream_out(self, *a, **kw):
        return self.cmd((), *a, **kw).stream_out()

    async def __call__(self, *a: list[Any], _list: bool = False, **kw: dict[Key, Any]) -> Caller:
        """
        Process a direct call.

        This makes some kind of best effort to unpack the result.
        If @_list is False, always returns a dict.
        If @_list is True, always returns a list.
        """
        res = await Caller(self, ((), a, kw))
        if res.kw:
            if _list:
                raise ValueError("has dict", res)
            if res.args:
                return res
            return res.kw
        args = res.args
        if not _list and len(args) == 1:
            return args[0]
        return args

    def sub_at(self, prefix: Path, may_stream:bool=False) -> SubMsgSender:
        """
        Returns a SubMsgSender
        """
        return SubMsgSender(self.root, self._path + prefix)

    def __getattr__(self, x):
        """
        Returns a SubMsgSender for this name
        """
        return self.sub_at(Path(x))


class MsgHandler(BaseMsgHandler):
    """
    Something that handles messages.

    Implement ``call(self, *a, *kw)`` and/or ``call_NAME(self, *a, *kw)``
    for simple method calls.

    Implement ``stream(self, *a, *kw)`` and/or ``stream_NAME(self, *a,
    *kw)`` for streamed calls.

    Set ``doc`` or ``doc_NAME`` for call documentation strings.
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
            elif (str := getattr(self, f"stream{pref}", None)) is not None:
                return await msg.call_stream(self.stream)
            else:
                raise ShortCommandError(msg.cmd)

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
            if hasattr(sub, "handle"):
                sub = sub.handle
            return await sub(msg, rcmd)

        raise KeyError(scmd, msg.cmd, list(self.sub.keys()) if hasattr(self,"sub") else ())

    def find_handler(self, path, may_stream: bool = False) -> tuple[MsgHandler, Path] | Callable:
        """
        Do a path lookup and find a suitable subcommand.

        This is a shortcut finder that returns either a subroot+prefix
        tuple or something that's callable directly. Implementing the
        latter for streams is TODO.
        """
        return self, path

    @asynccontextmanager
    async def _ctx(self):
        raise NotImplementedError
