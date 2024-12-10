"""
Common code for backends.

Currently the only backend supported is MQTT, but who knows.
"""

from __future__ import annotations

import anyio
import logging
from abc import ABCMeta, abstractmethod
from contextlib import asynccontextmanager

from attrs import define,field

from moat.lib.codec import get_codec as _get_codec
from moat.util import CtxObj, NotGiven, Path, Root, RootPath, attrdict

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.codec import Codec
    from moat.link.meta import MsgMeta

    from typing import Any, AsyncIterator, Self, ClassVar


__all__ = ["get_backend", "get_codec", "Backend", "Message", "RawMessage"]


def get_codec(name):
    "Codec loader; replaces 'std-' prefix with 'moat.util.'"
    if name[0:4] == "std-":
        name = "moat.util." + name[4:]
    return _get_codec(name)


@define
class Message[TData]:
    """
    An incoming message.
    """

    topic:Path = field()
    data:TData = field()
    meta:MsgMeta = field()
    orig:Any = field(repr=False)

    raw:ClassVar[bool] = False

    def __class_getitem__(cls, TData):
        return cls  # for now

class RawMessage(Message):
    "A message that couldn't be decoded / shouldn't be encoded"

    exc:Exception = field(default=None)
    raw:ClassVar[bool] = True


class Backend(CtxObj, metaclass=ABCMeta):
    "Base class for messaging backends"

    _tg: anyio.abc.TaskGroup
    _njobs: int = 0
    _ended: anyio.Event | None = None

    def __init__(self, cfg: attrdict, name: str):
        self.cfg = cfg
        self.name = name
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
        codec: Codec | None = None,
        raw: bool | None = False,
        retained: bool = True,
        echo: bool = False,
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
        self,
        subpath: Path,
        msg: str | None = None,
        data: Any = None,
        exc: Exception | None = None,
        **kw,
    ):
        """
        Send a somewhat-free-form error message.
        """
        if not isinstance(subpath[0], RootPath):
            subpath = Root / "error" + subpath
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
