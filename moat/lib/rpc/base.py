"""
Base classes for command handlers.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager

from moat.util import NotGiven
from moat import DOC
from moat.lib.micro import ACM, AC_exit, L, TaskGroup
from moat.lib.path import Path
from moat.lib.stream import Base
from moat.util.exc import ungroup

from .const import SD_BOTH, SD_IN, SD_NONE, SD_OUT
from .errors import NotReadyError, ShortCommandError

from typing import TYPE_CHECKING

if TYPE_CHECKING or DOC:
    from contextlib import AbstractContextManager
    from types import EllipsisType  # noqa:TC003

    from moat.lib.path import PathElem

    from .msg import Msg  # noqa:TC001

    from collections.abc import Awaitable, Callable, Mapping
    from typing import Any, Self

    Key = str | int | bool
    OptDict = Mapping[str, Any] | None

__all__ = ["BaseMsgHandler", "MsgHandler", "MsgSender"]


class Caller:
    """
    This is the Wrapper returned by `MsgSender.cmd`. It can be *await*ed
    (direct RPC call), or used as an async context manager (data streaming).

    The context manager yields an async iterator for incoming messages.

    .. seealso: moat.lib.rpc.Msg

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
        Args:
            sender: the MsgSender on which we call :py:meth:`MsgSender.handle` to get the result.
            data: (cmd,args,kw) tuple.
            _list: can be
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

    async def __aenter__(self) -> Msg:
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

        Args:
            size: length of the incoming queue
        """
        assert not self._dir
        self._dir = SD_BOTH
        self._qlen = size
        return self

    def stream_in(self, size: int = 42) -> Self:
        """mark as only streaming in.

        Args:
            size: length of the incoming queue
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
    Somewhat-abstract superclass for anything that accepts messages.
    """

    def handle(self, msg: Msg, rcmd: list[PathElem]) -> Awaitable[None]:
        """
        Handle this message stream.

        Args:
            msg: the message to process.
            rcmd: the inverted command prefix. Hierarchical handlers chop an
                  element off the end.
        """
        raise NotImplementedError


class MsgSender(BaseMsgHandler):
    """
    This class is the client-side API of the MoaT Command multiplexer.

    It is typically returned by the :meth:`MsgHandler.sender` method. The
    MsgHandler's :meth:`handle` method processes messages from the remote side,
    while this class accepts local messages and forwards them to the
    remote.
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

    def handle(self, msg: Msg, rcmd: list[PathElem]) -> Awaitable[None]:
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
        Resolve the given prefix, as far as possible.

        Returns a Callable, typically a :class:`SubMsgSender` — but
        possibly a method if the path can be resolved and *cmd* is `True`.
        """
        res = self.root.find_handler(prefix, cmd=cmd)
        if isinstance(res, tuple):
            root, rem = res
            if rem:
                return SubMsgSender(root, rem, caller=caller or self.Caller_)
            return MsgSender(root)
        return res

    def cfg_at(self, p: Path):
        "returns a CfgStore object that accesses the config at this subpath"

        from moat.lib.rpc import CfgStore  # noqa: PLC0415

        return CfgStore(self, p)

    def add_sub(self, elem: str):
        """
        Ensures that ``self.ELEM`` is a SubMsgSender.
        """
        if hasattr(self, elem):
            sb = getattr(self, elem)
            assert isinstance(sb, SubMsgSender)
        else:
            sb = self.sub_at(Path.build((elem,)))
            setattr(self, elem, sb)
        return sb


class SubMsgSender(MsgSender):
    """
    This `MsgSender` subclass auto-prefixes a path to all calls.

    Thus,

    >>> async with some_handler() as h:
    ...     h.add_sub("a")
    ...     await h.a.b.c()

    is the same as

    >>> async with some_handler() as h, h.sub_at(P("a.b")) as hab:
    ...     await hab.c()

    The additional context also verifies that the remote link is up
    (or rather, waits for it to *be* up).

    An empty path is OK.
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

    def __repr__(self):
        return f"<{self.__class__.__name__}:{self.root} {self._path}"

    @property
    def path(self):
        "The subpath accessible with this object"
        return self._path

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

    def handle(self, msg: Msg, rcmd: list[PathElem]) -> Awaitable[None]:
        """
        Forward the message, as directed by :py:attr:`path`.
        """
        rcmd.extend(self._rpath)
        return self._root.handle(msg, rcmd)

    def cmd(self, cmd: Path, *a: list[Any], **kw: dict[Key, Any]) -> Caller:
        """
        Run a command.

        The result of this call can be used both as an Awaitable (straight
        method call) and an async context manager (streaming):

        >>> res = await hdl.cmd(P("foo"),42)
        >>> async with hdl.cmd(P("times_two")) as m:
        ...     async for msg, in m:
        ...         m.send(msg*2)
        """
        # The path is modified later, when the Caller object
        # calls our .handle method
        return Caller(self, (cmd, a, kw))

    def stream(self, *a, **kw):
        return self.cmd((), *a, **kw).stream()

    def stream_in(self, *a, **kw):
        return self.cmd((), *a, **kw).stream_in()

    def stream_out(self, *a, **kw):
        return self.cmd((), *a, **kw).stream_out()

    def __call__(
        self, *a: list[Any], _list: bool | EllipsisType | None = None, **kw: dict[Key, Any]
    ) -> Caller:
        """
        Process a direct call.

        This makes some kind of best effort to unpack the result.
        If ``_list`` is False, always returns a dict.
        If ``_list`` is True, always returns a list.

        Args:
            _list: Unpacking mode.
        """
        return self.Caller_(self.root, (self._path, a, kw), _list=_list)

    def sub_at(self, prefix: Path, caller=None) -> SubMsgSender:
        """
        Returns a SubMsgSender
        """
        return SubMsgSender(self.root, self._path + prefix, caller=caller or self.Caller_)

    def __getattr__(self, x):
        """
        Returns a SubMsgSender for this name
        """
        return self.sub_at(Path.build((x,)))


class MsgHandler(Base, BaseMsgHandler):
    """
    Message dispatching, using a Path-based prefix.

    Implement ``cmd(self, *a, *kw)`` and/or ``cmd_NAME(self, *a, *kw)``
    for simple method calls.

    Implement ``stream(self, msg)`` and/or ``stream_NAME(self,
    msg)`` for streamed calls.

    Use ``doc`` or ``doc_NAME`` for basic call introspection.

    Set the SKIP_RDY class attribute to allow readiness checks for
    subcommands to pass through even if the handler itself is not ready.
    """

    SKIP_RDY = False

    @property
    def root(self):  # noqa: D102
        return self

    @property
    def sender(self):
        """
        If you implement a ``MsgHandler`` that controls a remote link,
        override this method to return a MsgSender that transmits to the
        remote side.

        Raises `NotImplementedError`.
        """
        if sys.implementation.name == "micropython":
            return None
        raise NotImplementedError

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
        if len(path) > 1:
            sub = getattr(self, name)  # must exist
            with sub.delegate(name[1:], service):
                yield self
        else:
            if hasattr(self, name):
                raise RuntimeError(f"{name}: already known")
            setattr(self, name, service)
            try:
                yield self
            finally:
                delattr(self, name)

    async def handle(self, msg: Msg, rcmd: list[PathElem], *prefix: list[str]):
        """
        Process the message.

        * If the command is ``XX.doc_``, return ``self.doc_XX``. This should be
          a class attribute.

        * If the command ends with ``rdy_``, check for readiness before
          further processing (if any).

        * Multi-step commands ``XX.*`` are handled by the ``sub_XX`` method.
          (If that is a class instance: call its ``handle`` method.)

        * Non-streaming commands are processed by ``cmd_XX`` if it exists.

        * Otherwise, commands are processed by ``stream_XX``.

        * If that doesn't exist, raise a `KeyError`.

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
        # First test if it's a readiness check.
        is_rdy = False
        if rcmd[0] == "rdy_":
            if (
                L
                and not getattr(self, "SKIP_RDY", False)
                and hasattr(self, "wait_ready")
                and await self.wait_ready(wait=True)
            ):
                raise NotReadyError(msg.cmd, rcmd)
            is_rdy = True

        # Find a subcommand.
        scmd = rcmd.pop()
        if (sub := self.find_sub(scmd, pref)) is not None:
            if hasattr(sub, "handle"):
                sub = sub.handle
            return await sub(msg, rcmd)

        if is_rdy:
            return await msg.result(None)

        raise KeyError(
            scmd,
            self.cfg_name,
            msg.cmd,
            list(self.sub.keys()) if hasattr(self, "sub") else (),
        )

    def find_sub(self, scmd: str, prefix: str = "") -> Callable | None:
        """
        Resolve a subcommand.

        Args:
            scmd: the subcommand to look up.
            prefix: any command prefix (deprecated-ish).

        The default implementation uses sub{pref}_{scmd} attributes.
        """
        return getattr(self, f"sub{prefix}_{scmd}", None)

    def find_handler(self, path, cmd: bool = False) -> tuple[MsgHandler, Path] | Callable:
        """
        Do a path lookup and find a suitable subcommand.

        This is a shortcut finder that returns either a subroot+prefix
        tuple or something that's callable directly. Implementing the
        latter is TODO.
        """
        cmd  # noqa:B018
        return self, path

    doc_dir_ = dict(
        _d="directory",
        v="bool:verbose",
        _r=dict(c=["str:commands"], d=["str:modules"], j="bool:callable"),
    )

    async def cmd_dir_(self, v=True):
        """
        Rudimentary introspection. Returns a dict with
        a list of available commands @c,
        iterators @i, and submodules @d.
        j=True if callable directly.

        If @v ("visible") is set (the default),
        this does not return hidden commands.
        """
        c = []
        s = []
        res = {}

        for k in dir(self):
            if v is (k[-1] == "_"):
                continue
            if k.startswith("cmd_"):
                c.append(k[4:])
            elif k.startswith("stream_"):
                s.append(k[7:])
            elif k == "cmd":
                res["C"] = True
            elif k == "stream":
                res["S"] = True
        if c:
            res["c"] = c
        if s:
            res["s"] = s
        return res

    if L:
        doc_rdy_ = dict(_d="check readiness", w="bool:wait for it?")

        def cmd_rdy_(self, w=True) -> Awaitable:
            """
            Check if / wait for readiness.

            See :meth:`wait_ready` for return values.
            """
            return self.wait_ready(wait=w)

        async def wait_ready(self, wait: bool = True) -> bool | None:
            """
            Check if this handler is ready.

            Args:
                wait: whether to sleep until ready.

            Returns:
                * ``True`` if stopped
                * ``False`` if it already running
                * ``None`` if the command has (or would have, if
                  *wait* is False) waited for it to become ready.
            """
            wait  # noqa:B018
            return False
