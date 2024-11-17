from __future__ import annotations

import anyio
import logging
import random
from abc import ABCMeta, abstractmethod
from contextlib import asynccontextmanager

from moat.lib.codec import Codec
from moat.util import CtxObj, NotGiven, Root, RootPath, attrdict

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import AsyncIterator, Message

__all__ = ["get_backend", "get_codec", "Backend", "Message", "RawMessage"]


def get_codec(name):
    "Codec loader; replaces 'std-' prefix with 'moat.util.'"
    if name[0:4] == "std-":
        name = "moat.util." + name[4:]
    return _get_codec(name)


class Message:
    """
    An incoming message.
    """

    raw = False

    def __init__(self, topic: Path, data: Any, meta: MsgMeta, orig: Any = None):
        self.topic = topic
        self.data = data
        self.meta = meta
        self.orig = orig


class RawMessage(Message):
    "A message that couldn't be decoded / shouldn't be encoded"

    raw = True

    def __init__(
        self, topic: Path, data: Any, meta: MsgMeta, orig: Any = None, exc: Exception = None
    ):
        self.topic = topic
        self.data = data
        self.meta = meta
        self.orig = orig
        self.exc = exc


class Backend(CtxObj, metaclass=ABCMeta):
    "Base class for messaging backends"

    _tg: anyio.abc.TaskGroup
    _njobs: int = 0
    _ended: anyio.Event | None = None

    def __init__(self, cfg: attrdict, name: str | None = None):
        self.cfg = cfg
        if name is None:
            name = cfg.get("client_id")
        if name is None:
            name = "c_" + "".join(
                random.choices("bcdfghjkmnopqrstvwxyzBCDFGHJKMNOPQRSTVWXYZ23456789", k=10)
            )
        self.name = name
        self.logger = logging.getLogger(f"moat.link.backend.{name}")

    @abstractmethod
    @asynccontextmanager
    async def connect(self, *a, **k) -> AsyncIterator[Self]:
        """
        This async context manager returns a connection to the backend.
        """

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterators[Self]:
        async with (
            anyio.create_task_group() as self._tg,
            self.connect(),
        ):
            yield self

    @abstractmethod
    @asynccontextmanager
    async def monitor(
        self, topic: Path, qos: int = None, codec: Codec | None = None, raw: bool | None = False
    ) -> AsyncIterator[AsyncIterator[Message]]:
        """
        Return an async iterator that listens to this topic.

        Set @raw to ``True`` to always get non-decoded messages.
        """

    @abstractmethod
    async def send(
        self, topic: Path, data: Any, codec: Codec | None = None, **kw: dict[str, Any]
    ) -> None:
        """
        Send this payload to this topic.
        """

    async def send_error(
        self, subpath: Path, msg: str = None, data: Any = None, exc: Exception | None = None, **kw
    ):
        if not isinstance(subpath[0], RootPath):
            subpath = Root / "error" + subpath
        if msg:
            kw["msg"] = msg
        if data is not NotGiven:
            kw["data"] = data
        if exc is not None:
            kw["exc"] = repr(exc)

        try:
            await self.send(subpath, kw, codec="std-cbor")
        except Exception:
            self.logger.exception(f"Failure to log error at {subpath}: {data!r}", exc_info=exc)
        else:
            self.logger.debug(f"Error at {subpath}: {data!r}", exc_info=exc)


def get_backend(cfg: dict, **kw) -> Backend:
    from importlib import import_module

    cfg = cfg["backend"]
    name = cfg["driver"]
    if "." not in name:
        name = "moat.link.backend." + name
    return import_module(name).Backend(cfg, **kw)
