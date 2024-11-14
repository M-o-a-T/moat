from __future__ import annotations

from abc import ABCMeta, abstractmethod
from contextlib import asynccontextmanager
import random

import anyio

from moat.util import CtxObj, NotGiven, attrdict

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import AsyncIterator, Message

__all__ = ["get_backend", "get_codec", "Backend", "Message", "RawMessage"]

def get_codec(name):
    "Codec loader; replaces 'std-' prefix with 'moat.util.'"
    if name[0:4] == "std-":
        name = "moat.util."+name[4:]
    return _get_codec(name)

class Message:
    def __init__(self, topic, data, prop, orig, **kw):
        self.topic = topic
        self.data = data
        self.prop = prop
        self.orig = orig
        self.meta = attrdict(kw)

class RawMessage:
    def __init__(self, topic, data, prop, orig, exc, **kw):
        self.topic = topic
        self.data = data
        self.prop = prop
        self.orig = orig
        self.exc = exc
        self.meta = attrdict(kw)


class Backend(CtxObj, metaclass=ABCMeta):
    _tg: anyio.abc.TaskGroup
    _njobs:int = 0
    _ended:anyio.Event|None = None

    def __init__(self, cfg:attrdict, name:str|None=None):
        self.cfg = cfg
        if name is None:
            name = cfg.get("client_id")
        if name is None:
            name = "c_"+"".join(random.choices("bcdfghjkmnopqrstvwxyzBCDFGHJKMNOPQRSTVWXYZ23456789", k=10))
        self.name = name

    @abstractmethod
    @asynccontextmanager
    async def connect(self, *a, **k):
        """
        This async context manager returns a connection to the backend.
        """

    @asynccontextmanager
    async def _ctx(self):
        async with (
                anyio.create_task_group() as self._tg,
                self.connect(),
                ):
            yield self

    @abstractmethod
    @asynccontextmanager
    async def monitor(self, topic: Path, qos:int=None) -> AsyncIterator[Message]:
        """
        Return an async iterator that listens to this topic.
        """

    @abstractmethod
    async def send(self, topic: Path, data: Any, **kw: dict[str,Any]) -> None:
        """
        Send this payload to this topic.
        """


def get_backend(cfg, **kw):
    from importlib import import_module

    cfg = cfg["backend"]
    name= cfg["driver"]
    if "." not in name:
        name = "moat.link.backend." + name
    return import_module(name).Backend(cfg, **kw)
