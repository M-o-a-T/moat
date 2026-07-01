"""
Asyncactor integration on top of MoaT-Link's MQTT backend.

The :mod:`asyncactor` package implements the gossip-style "who's up?"
protocol that the kv job runner uses to coordinate cluster work.  This
module wires the actor up to the MoaT-Link client's pub/sub primitives
so the same code can run on top of the link.
"""

from __future__ import annotations

from asyncactor import Actor
from asyncactor.abc import MonitorStream, Transport

from typing import TYPE_CHECKING, Any, Self

if TYPE_CHECKING:
    from moat.lib.path import Path
    from moat.link.client import LinkSender


__all__ = [
    "ActorState",
    "BrokenState",
    "CompleteState",
    "DetachedState",
    "LinkActor",
    "PartialState",
]


class LinkActor(Actor):
    """An :class:`asyncactor.Actor` running on the MoaT-Link MQTT backend."""

    def __init__(self, link: LinkSender, *a: Any, topic: Path, **kw: Any) -> None:
        super().__init__(_LinkTransport(link, topic), *a, **kw)


class _LinkTransport(Transport):
    """Adapter exposing the MoaT-Link pub/sub interface to an :class:`Actor`."""

    link: LinkSender
    topic: Path

    def __init__(self, link: LinkSender, topic: Path) -> None:
        self.link = link
        self.topic = topic

    def monitor(self) -> _LinkMonitor:
        return _LinkMonitor(self)

    async def send(self, payload: Any) -> None:
        await self.link.send(self.topic, payload, retain=False)


class _LinkMonitor(MonitorStream):
    """One MQTT subscription on behalf of an :class:`Actor`."""

    _link: LinkSender
    _topic: Path
    _mon1: Any = None
    _mon2: Any = None
    _it: Any = None

    def __init__(self, transport: _LinkTransport) -> None:
        super().__init__(transport)
        self._link = transport.link
        self._topic = transport.topic

    async def __aenter__(self) -> Self:
        self._mon1 = self._link.monitor(self._topic)
        self._mon2 = await self._mon1.__aenter__()
        return self

    async def __aexit__(self, *tb: object) -> Any:
        return await self._mon1.__aexit__(*tb)

    def __aiter__(self) -> Self:
        self._it = self._mon2.__aiter__()
        return self

    async def __anext__(self) -> Any:
        msg = await self._it.__anext__()
        return msg.data


class ActorState:
    """Base class for actor-related state notifications.

    Args:
        msg: the originating actor event, if any.
    """

    msg: Any

    def __init__(self, msg: Any = None) -> None:
        self.msg = msg

    def __repr__(self) -> str:
        return f"<{self.__class__.__name__}:{self.msg!r}>"


class BrokenState(ActorState):
    """No actor messages have been seen for a while."""


class DetachedState(ActorState):
    """This node is currently alone in its actor group."""


class PartialState(ActorState):
    """Some, but not all, group members are reachable."""


class CompleteState(ActorState):
    """All members of the actor group are reachable."""
