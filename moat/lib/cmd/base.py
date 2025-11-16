"""
Base classes for command handlers.
"""

from __future__ import annotations

from contextlib import contextmanager

from moat.util import NotGiven, Path
from moat.util.compat import ACM, AC_exit, L, TaskGroup, log, shield
from moat.util.exc import ungroup

from .const import B_ERROR, B_STREAM, E_CANCEL, E_ERROR, SD_BOTH, SD_IN, SD_NONE, SD_OUT
from .errors import NotReadyError, ShortCommandError

from typing import TYPE_CHECKING

_link_id = 0

if TYPE_CHECKING:
    from contextlib import AbstractContextManager
    from types import EllipsisType

    from .msg import Msg

    from collections.abc import Awaitable, Callable, Mapping, Sequence
    from typing import Any, Self

    Key = str | int | bool
    OptDict = Mapping[str, Any] | None


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
            if isinstance(exc, Exception):
                log("Err after end: %r %r", self, exc, err=exc)
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
                    except Exception as ex:
                        log("Unable to send: %r %r / %r", self, exc, ex)
                        pass

    @property
    def end_both(self) -> bool:  # noqa: D102
        if self._remote and not self._remote.end_here:
            return False
        return self._end

    @property
    def end_here(self) -> bool:  # noqa: D102
        return self._end

    @property
    def end_there(self) -> bool:  # noqa: D102
        if self._remote is None:
            return True
        return self._remote.end_here

    @property
    def remote(self):  # noqa: D102
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
            except Exception:  # noqa:S110
                pass

    def set_remote(self, remote: MsgLink):
        """
        Set (or change) my remote for @remote.

        The old remote, if any, is `kill`ed.
        """
        rem = self._remote
        if rem is not None:
            rem._remote = None  # noqa: SLF001
            rem.set_end()
        self._remote = remote

    def __repr__(self):
        return (
            f"<{self.__class__.__name__}:L{self.link_id} "
            f"r{'=L' + str(self._remote.link_id) if self._remote else '-'}>"
        )


class Caller:
    """
    This is the Wrapper returned by `MsgSender.cmd`.

    You should not instantiate this class directly.
    """

    _qlen = 0

    def __init__(
        self,
        sender: MsgSender,
        data: tuple[str | Path, list | tuple, dict],
        _list: bool | EllipsisType | None = NotGiven,
    ):
        """
        @sender: the MsgSender on which we call ``.handle`` to get the result.
        @data: (cmd,args,kw) tuple.
        @_list: can be
          - NotGiven: return the message object
          - True: return a list
          - False: return a dict
          - None: best effort (single/map/list/message object)
        """
        self.data = data
        self.sender = sender
        self._dir = SD_NONE
        self._list = _list

    def __await__(self):
        "makes this object awaitable, CPython"
        return self._call().__await__()

    def __iter__(self):
        "makes this object awaitable, MicroPython"
        # this depends on µPy doing the right thing
        return self._call()

    async def _call(self):
        "helper for __await__ that calls the remote side"
        from .msg import Msg  # noqa: PLC0415

        msg = Msg.Call(*self.data)

        await self.sender.handle(msg, msg.rcmd)
        await msg.wait_replied()

        if self._list is NotGiven:
            return msg

        if self._list is True:
            # always return a list
            if msg.kw:
                raise ValueError("has dict", msg)
            return msg.args

        if self._list is False:
            # always return a dict
            if msg.args:
                raise ValueError("has args", msg)
            return msg.kw

        if kw := msg.kw:
            if msg.args:
                # return the message object if both kw and args are set
                return msg
            # return a dict if only kw is set
            return kw

        args = msg.args
        if len(args) == 1:
            # return a single arg directly
            return args[0]
        # otherwise return all of them (if any)
        return args

    async def __aenter__(self):
        acm = ACM(self)
        try:
            if not self._dir:
                self._dir = SD_BOTH

            from .msg import Msg  # noqa: PLC0415

            m1 = Msg.Call(*self.data)

            tg = await acm(TaskGroup())
            m2 = await acm(m1.ensure_remote())
            # m2 is the one with the command data
            tg.start_soon(self.sender.handle, m2, m2.rcmd)
            await acm(m1._stream_call(self._dir))  # noqa: SLF001
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

    Caller_: type[Caller] = Caller

    def __init__(self, root: MsgHandler):
        """
        This class accepts client-side MoaT-cmd calls and turns them into
        messages.
        """
        self._root = root

    async def __aenter__(self):
        return self

    async def __aexit__(self, *tb):
        pass

    @property
    def root(self):  # noqa: D102
        return self._root

    def set_root(self, root):  # noqa: D102
        if type(self) is not MsgSender:
            raise RuntimeError("not in a subclass")
        assert not isinstance(root, MsgSender)
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

    def sub_at(self, prefix: Path, caller=None, cmd: bool = False) -> MsgSender:
        """
        Returns a SubMsgSender if the path cannot be resolved locally.
        """
        res = self.root.find_handler(prefix, cmd=cmd)
        if isinstance(res, tuple):
            root, rem = res
            if rem:
                return SubMsgSender(root, rem, caller=caller or self.Caller_)
            return MsgSender(root)
        return res

    def cfg_at(self, p: Path):
        "returns a CfgStore object at this subpath"

        from moat.micro.cmd.tree.dir import CfgStore  # noqa: PLC0415

        return CfgStore(self, p)

    def add_sub(self, elem: str):
        """
        Ensures that `self.ELEM` is a SubMsgSender.
        """
        if hasattr(self, elem):
            sb = getattr(self, elem)
            assert isinstance(sb, SubMsgSender)
        else:
            sb = self.sub_at(Path(elem))
            setattr(self, elem, sb)
        return sb


class SubMsgSender(MsgSender):
    """
    This `MsgSender` subclass auto-prefixes a path to all calls.
    """

    def __init__(self, root: MsgHandler, path: Path, caller=None):
        """
        Setup.
        """
        super().__init__(root)
        self._path = path
        self._rpath = list(path)
        self._rpath.reverse()
        if caller is not None:
            self.Caller_ = caller

    async def __aenter__(self):
        "Ensure that the called object is ready for service"
        try:
            msg = await self.cmd(["rdy_"])
        except KeyError:
            pass  # can't do it. Oh well.
        else:
            if msg[0]:
                raise NotReadyError(self)
        return await super().__aenter__()

    def handle(self, msg: Msg, rcmd: list) -> Awaitable[None]:  # noqa: D102
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

    def stream(self, *a, **kw):  # noqa: D102
        return self.cmd((), *a, **kw).stream()

    def stream_in(self, *a, **kw):  # noqa: D102
        return self.cmd((), *a, **kw).stream_in()

    def stream_out(self, *a, **kw):  # noqa: D102
        return self.cmd((), *a, **kw).stream_out()

    def __call__(
        self, *a: list[Any], _list: bool | EllipsisType | None = None, **kw: dict[Key, Any]
    ) -> Caller:
        """
        Process a direct call.

        This makes some kind of best effort to unpack the result.
        If @_list is False, always returns a dict.
        If @_list is True, always returns a list.
        """
        return self.Caller_(self.root, (self._path, a, kw), _list=_list)

    def sub_at(self, prefix: Path, caller=None) -> SubMsgSender:
        """
        Returns a SubMsgSender
        """
        return SubMsgSender(self.root, self._path + prefix, caller=caller or self.Caller_)

    def cfg_at(self, p: Path):
        "returns a CfgStore object at this subpath"

        from moat.micro.cmd.tree.dir import CfgStore  # noqa: PLC0415

        return CfgStore(self, p)

    def __getattr__(self, x):
        """
        Returns a SubMsgSender for this name
        """
        return self.sub_at(Path.build((x,)))


class MsgHandler(BaseMsgHandler):
    """
    Something that handles messages.

    Implement ``cmd(self, *a, *kw)`` and/or ``cmd_NAME(self, *a, *kw)``
    for simple method calls.

    Implement ``stream(self, msg)`` and/or ``stream_NAME(self,
    msg)`` for streamed calls.

    Use ``doc`` or ``doc_NAME`` for (too-)basic call introspection.
    """

    @property
    def root(self):  # noqa: D102
        return self

    @contextmanager
    def delegate(self, path: Path, service: MsgHandler) -> AbstractContextManager[Self]:
        """
        Tell this handler to delegate messages that start with this path
        to that handler.

        Args:
            path: the prefix to delegate
            service: the service to call

        This is a context manager.
        """
        if len(path) == 0:
            raise RuntimeError(f"{path}: cannot be empty")
        name = f"sub_{path[0]}"
        if hasattr(self, name):
            raise RuntimeError(f"{name}: already known")
        if len(path) > 1:
            sub = getattr(self, name)  # must exist
            with sub.delegate(name[1:], service):
                yield self
        else:
            setattr(self, name, service)
            try:
                yield self
            finally:
                delattr(self, name)

    async def handle(self, msg: Msg, rcmd: list, *prefix: list[str]):
        """
        Process the message.
        """
        pref = "_" + "_".join(prefix) if prefix else ""

        # Process direct calls.
        if not rcmd:
            if not msg.can_stream and (cmd := getattr(self, f"cmd{pref}", None)) is not None:
                return await msg.call_simple(cmd)
            elif getattr(self, f"stream{pref}", None) is not None:
                return await msg.call_stream(self.stream)
            else:
                raise ShortCommandError(msg.cmd)

        # Process requests for documentation.
        if len(rcmd) <= 2 and rcmd[0] == "doc_":
            if msg.args or msg.kw:
                raise TypeError("doc", msg.args, msg.kw)
            if (
                doc := getattr(
                    self, f"doc{pref}_{rcmd[1]}" if len(rcmd) > 1 else f"doc{pref}", None
                )
            ) is not None:
                return await msg.result(doc)

        # Process command handlers of this class.
        if len(rcmd) == 1:
            if (
                not msg.can_stream
                and (cmd := getattr(self, f"cmd{pref}_{rcmd[0]}", None)) is not None
            ):
                return await msg.call_simple(cmd)
            if (cmd := getattr(self, f"stream{pref}_{rcmd[0]}", None)) is not None:
                return await msg.call_stream(cmd)

        # Neither of the above.
        # First check if it's a readiness check.
        is_rdy = False
        if rcmd[0] == "rdy_":
            if L and await self.wait_ready(wait=True):
                raise NotReadyError(msg.cmd, rcmd)
            is_rdy = True

        # Find a subcommand.
        scmd = rcmd.pop()
        if (sub := getattr(self, f"sub{pref}_{scmd}", None)) is not None:
            if hasattr(sub, "handle"):
                sub = sub.handle
            return await sub(msg, rcmd)

        if is_rdy:
            return await msg.result(None)

        raise KeyError(scmd, msg.cmd, list(self.sub.keys()) if hasattr(self, "sub") else ())

    def find_handler(self, path, cmd: bool = False) -> tuple[MsgHandler, Path] | Callable:
        """
        Do a path lookup and find a suitable subcommand.

        This is a shortcut finder that returns either a subroot+prefix
        tuple or something that's callable directly. Implementing the
        latter is TODO.
        """
        cmd  # noqa:B018
        return self, path
