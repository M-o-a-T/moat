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

from moat.util import CtxObj, NotGiven, Path, Root, attrdict, get_codec

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mqttproto import QoS

    from moat.lib.codec import Codec
    from moat.link.meta import MsgMeta

    from collections.abc import AsyncIterator
    from typing import Any, ClassVar, Literal, Self


__all__ = ["Backend", "Message", "RawMessage", "get_backend", "get_codec"]


@define
class Message[TData]:
    """
    An incoming message.
    """

    topic: Path = field()
    data: TData = field()
    meta: MsgMeta = field()
    prop: dict[str, Any] = field(repr=False)
    retain: bool | None = field(default=False)

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

    def __init__(self, cfg: attrdict, name: str, id: str):
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
        if subpath.prefix is None:
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
    from importlib import import_module  # noqa: PLC0415

    cfg = cfg["backend"]
    name = cfg["driver"]
    if "." not in name:
        name = "moat.link.backend." + name
    return import_module(name).Backend(cfg, **kw)
