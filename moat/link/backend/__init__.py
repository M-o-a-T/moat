"""
Common code for backends.

Currently the only backend supported is MQTT, but who knows.
"""

from __future__ import annotations

import anyio
import logging
from abc import ABCMeta, abstractmethod
from contextlib import asynccontextmanager

from attrs import define, field

from moat.util import CtxObj, NotGiven, Path, Root, RootPath, attrdict, get_codec

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.codec import Codec
    from moat.link.meta import MsgMeta

    from typing import Any, Self, ClassVar
    from collections.abc import AsyncIterator


__all__ = ["get_backend", "get_codec", "Backend", "Message", "RawMessage"]


@define
class Message[TData]:
    """
    An incoming message.
    """

    topic: Path = field()
    data: TData = field()
    meta: MsgMeta = field()
    prop: dict[str,Any] = field()
    retain: bool|None = field(default=False)

    raw: ClassVar[bool] = False

    def __class_getitem__(cls, TData):
        return cls  # for now


@define
class RawMessage(Message):
    "A message that couldn't be decoded / shouldn't be encoded"

    exc: Exception = field(default=None)
    raw: ClassVar[bool] = True


class Backend(CtxObj, metaclass=ABCMeta):
    "Base class for messaging backends"

    _tg: anyio.abc.TaskGroup
    _njobs: int = 0
    _ended: anyio.Event | None = None

    def __init__(self, cfg: attrdict, name: str, id:str):
        self.cfg = cfg
        self.name = name
        self.id = id
        self.logger = logging.getLogger(f"moat.link.backend.{name}")

    @abstractmethod
    @asynccontextmanager
    async def connect(self, *a, **k) -> AsyncIterator[Self]:
        """
        This async context manager returns a connection to the backend.
        """

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Self]:
        async with (
            anyio.create_task_group() as self._tg,
            self.connect(),
        ):
            yield self

    @abstractmethod
    @asynccontextmanager
    async def monitor(
        self,
        topic: Path,
        qos: QoS | None = None,
        codec: Codec | None | Literal[NotGiven] = NotGiven,
        raw: bool | None = False,
        echo: bool = False,
        no_local: bool = False,
        subtree: bool = False,
    ) -> AsyncIterator[AsyncIterator[Message]]:
        """
        Return an async iterator that listens to this topic.

        Set @raw to ``True`` to always get non-decoded messages.
        """

    @abstractmethod
    async def send(
        self,
        topic: Path,
        data: Any,
        codec: Codec | None | Literal[NotGiven] = NotGiven,
        **kw: Any,
    ) -> None:
        """
        Send this payload to this topic.
        """

    async def send_error(
        self,
        subpath: Path,
        msg: str | None = None,
        data: Any = None,
        exc: Exception | None = None,
        **kw: Any,
    ):
        """
        Send a somewhat-free-form error message.
        """
        if not isinstance(subpath[0], RootPath):
            subpath = Root.get() / "error" + subpath
        if msg:
            kw["msg"] = msg
        if data is not NotGiven:
            kw["data"] = data
        if exc is not None:
            kw["exc"] = repr(exc)
        # TODO include the backtrace?

        try:
            await self.send(subpath, kw, codec="std-cbor")
        except Exception:
            self.logger.exception("Failure to log error at %s: %r", subpath, data, exc_info=exc)
        else:
            self.logger.debug("Error at %s: %r", subpath, data, exc_info=exc)


def get_backend(cfg: dict, **kw) -> Backend:
    """
    Fetch the backend named in the config and initialize it.
    """
    from importlib import import_module

    cfg = cfg["backend"]
    name = cfg["driver"]
    if "." not in name:
        name = "moat.link.backend." + name
    return import_module(name).Backend(cfg, **kw)
