from __future__ import annotations  # noqa: D100

import anyio
import logging
import time
from contextlib import asynccontextmanager, suppress
from enum import Enum, auto
from functools import partial

from attrs import define, field
from transitions_aio.extensions.factory import MachineFactory

from moat.util import CtxObj, NotGiven, P, attrdict, srepr
from moat.lib.priomap import TimerMap
from moat.util.broadcast import Broadcaster

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from transitions_aio import EventData

    from moat.util import Path
    from moat.link.client import Link

    from collections.abc import Awaitable
    from typing import Any

__all__ = ["HostList", "ServiceMon"]

logger = logging.getLogger(__name__)


#
# Monitoring
#
class HostState(Enum):
    # constants
    INIT = "in"
    NEW = "nw"
    DOWN = "dn"  # id state=down seen
    UP = "up"
    TIMEOUT = "tm"  # no ping for some time, error generated
    STALE = "sl"  # superseded
    DROP = "xx"  # no ping for a long time, entry dropped

    # We want "id" and "ping" messages.
    # "host" is an additional "name this host" signal.
    ONLY_I = "oi"  # only host/id seen
    ONLY_P = "op"  # only ping seen


class HostEvent(Enum):
    INIT = auto()
    MSG_HOST = auto()
    MSG_PING = auto()
    MSG_ID = auto()

    MSG_DOWN = auto()
    DEL_HOST = auto()  # Service gets dropped, or replaced
    DEL_ID = auto()

    TIMEOUT = auto()


_S = HostState
_E = HostEvent


# @add_state_features(MonTimeout)
class HostMachine(MachineFactory.get_predefined(graph=True, asyncio=True)):
    def __init__(self, host):
        states = [
            dict(name=_S.INIT),
            dict(name=_S.NEW),
            dict(name=_S.DOWN),
            dict(name=_S.UP),
            dict(name=_S.TIMEOUT),
            dict(name=_S.STALE),
            dict(name=_S.DROP, final=True),
            dict(name=_S.ONLY_I),
            dict(name=_S.ONLY_P),
        ]
        transitions = [
            dict(trigger=_E.INIT, source=_S.INIT, dest=_S.NEW),
            dict(trigger=_E.MSG_HOST, source=_S.NEW, dest=_S.ONLY_I),
            dict(trigger=_E.MSG_ID, source=_S.NEW, dest=_S.ONLY_I),
            dict(trigger=_E.MSG_PING, source=_S.NEW, dest=_S.ONLY_P),
            dict(trigger=_E.MSG_DOWN, source=_S.NEW, dest=_S.DROP),
            dict(trigger=_E.DEL_HOST, source=_S.NEW, dest=_S.DROP),
            dict(trigger=_E.DEL_ID, source=_S.NEW, dest=_S.DROP),
            dict(trigger=_E.TIMEOUT, source=_S.NEW, dest=_S.DROP),
            dict(trigger=_E.MSG_HOST, source=_S.ONLY_I, dest=_S.ONLY_I),
            dict(trigger=_E.MSG_ID, source=_S.ONLY_I, dest=_S.ONLY_I),
            dict(trigger=_E.MSG_PING, source=_S.ONLY_I, dest=_S.UP),
            dict(trigger=_E.MSG_DOWN, source=_S.ONLY_I, dest=_S.DROP),
            dict(trigger=_E.DEL_HOST, source=_S.ONLY_I, dest=_S.DROP),
            dict(trigger=_E.DEL_ID, source=_S.ONLY_I, dest=_S.DROP),
            dict(trigger=_E.TIMEOUT, source=_S.ONLY_I, dest=_S.DROP),
            dict(trigger=_E.MSG_HOST, source=_S.ONLY_P, dest=_S.ONLY_P),
            dict(trigger=_E.MSG_ID, source=_S.ONLY_P, dest=_S.UP),
            dict(trigger=_E.MSG_PING, source=_S.ONLY_P, dest=None),
            dict(trigger=_E.MSG_DOWN, source=_S.ONLY_P, dest=_S.DROP),
            dict(trigger=_E.DEL_HOST, source=_S.ONLY_P, dest=_S.DROP),
            dict(trigger=_E.DEL_ID, source=_S.ONLY_P, dest=_S.DROP),
            dict(trigger=_E.TIMEOUT, source=_S.ONLY_P, dest=_S.DROP),
            dict(trigger=_E.MSG_HOST, source=_S.DOWN, dest=_S.DOWN),
            dict(trigger=_E.MSG_ID, source=_S.DOWN, dest=_S.DOWN),
            dict(trigger=_E.MSG_PING, source=_S.DOWN, dest=_S.DOWN),
            dict(trigger=_E.MSG_DOWN, source=_S.DOWN, dest=_S.DROP),
            dict(trigger=_E.DEL_HOST, source=_S.DOWN, dest=_S.DROP),
            dict(trigger=_E.DEL_ID, source=_S.DOWN, dest=_S.DROP),
            dict(trigger=_E.TIMEOUT, source=_S.DOWN, dest=_S.DROP),
            dict(trigger=_E.MSG_HOST, source=_S.UP, dest=_S.UP),
            dict(trigger=_E.MSG_ID, source=_S.UP, dest=_S.UP),
            dict(trigger=_E.MSG_PING, source=_S.UP, dest=None),
            dict(trigger=_E.MSG_DOWN, source=_S.UP, dest=_S.DOWN),
            dict(trigger=_E.DEL_HOST, source=_S.UP, dest=_S.DROP),
            dict(trigger=_E.DEL_ID, source=_S.UP, dest=_S.DROP),
            dict(trigger=_E.TIMEOUT, source=_S.UP, dest=_S.STALE),
            dict(trigger=_E.MSG_HOST, source=_S.TIMEOUT, dest=_S.TIMEOUT, after=host.drop_host),
            dict(trigger=_E.MSG_ID, source=_S.TIMEOUT, dest=_S.TIMEOUT, after=host.drop_id),
            dict(trigger=_E.MSG_PING, source=_S.TIMEOUT, dest=_S.TIMEOUT, after=host.drop_id),
            dict(trigger=_E.MSG_DOWN, source=_S.TIMEOUT, dest=_S.DROP),
            dict(trigger=_E.DEL_HOST, source=_S.TIMEOUT, dest=_S.DROP),
            dict(trigger=_E.DEL_ID, source=_S.TIMEOUT, dest=_S.DROP),
            dict(trigger=_E.TIMEOUT, source=_S.TIMEOUT, dest=_S.DROP),
            dict(trigger=_E.MSG_HOST, source=_S.STALE, dest=None),
            dict(trigger=_E.MSG_ID, source=_S.STALE, dest=None),
            dict(trigger=_E.MSG_PING, source=_S.STALE, dest=_S.UP),
            dict(trigger=_E.MSG_DOWN, source=_S.STALE, dest=None),
            dict(trigger=_E.DEL_HOST, source=_S.STALE, dest=None),
            dict(trigger=_E.DEL_ID, source=_S.STALE, dest=None),
            dict(trigger=_E.TIMEOUT, source=_S.STALE, dest=_S.DROP),
            dict(trigger=_E.MSG_HOST, source=_S.DROP, dest=None, after=host.re_init),
            dict(trigger=_E.MSG_ID, source=_S.DROP, dest=None, after=host.re_init),
            dict(trigger=_E.MSG_PING, source=_S.DROP, dest=None, after=host.re_init),
            dict(trigger=_E.MSG_DOWN, source=_S.DROP, dest=None, after=host.re_init),
            dict(trigger=_E.DEL_HOST, source=_S.DROP, dest=None, after=host.re_init),
            dict(trigger=_E.DEL_ID, source=_S.DROP, dest=None, after=host.drop_id),
            dict(trigger=_E.TIMEOUT, source=_S.DROP, dest=None, after=host.drop_both),
        ]
        for s in states:
            sn = s["name"].name.lower()
            if (cb := getattr(host, f"on_enter_{sn}", None)) is not None:
                s["on_enter"] = [cb]
            if (cb := getattr(host, f"on_exit_{sn}", None)) is not None:
                s["on_exit"] = [cb]

        super().__init__(
            # model=host,
            states=states,
            initial=HostState.INIT,
            transitions=transitions,
            auto_transitions=False,
            ignore_invalid_triggers=False,
            send_event=True,
            queued=True,
            after_state_change=[self._set_timeout, host.updated],
            on_final=host.drop_both,
        )
        self.host = host

    def _set_timeout(self, ed: EventData):
        host = ed.model.host
        host.mon.set_timeout(host)


@define(eq=False)
class Service:
    """Contains data for one particular service."""

    mon: HostList = field()
    id: str = field()

    # These get filled via path
    data: dict[str, dict] = field(factory=attrdict, init=False)
    machine: HostMachine = field(init=False)

    _last = field(default=0, init=False)

    def __attrs_post_init__(self):
        self.machine = HostMachine(self)
        self.data.h = dict()

    @property
    def state(self):
        return self.machine.state

    @property
    def timeout(self):
        "returns the timeout under `cfg.link.timout.ping`"
        if self.state is HostState.DROP:
            return 0  # error when looked up

        if self.state in (HostState.ONLY_I, HostState.TIMEOUT):
            val = "stale"
        elif self.state in (HostState.DOWN, HostState.STALE):
            val = "delete"
        else:
            val = "timeout"
        res = self.mon.cfg.timeout.ping[val]
        if self.last:
            age = time.time() - self.last
            res = min(res, max(self.mon.cfg.timeout.ping.min, age))
        return res

    def updated(self, evt):
        "queue update to Broadcaster"
        self.mon.updated(self, evt)

    def drop_id(self, _evt) -> Awaitable[None]:
        return self.mon.drop_id(self)

    def drop_host(self, _evt) -> Awaitable[None]:
        return self.mon.drop_host(self)

    async def drop_both(self, evt=None) -> None:
        evt  # noqa:B018
        await self.mon.drop_host(self)
        await self.mon.drop_id(self)

    @property
    def last(self):
        return self._last

    @last.setter
    def last(self, tm):
        if self._last < tm:
            self._last = tm

    def trigger(self, *args, **kwargs) -> Awaitable:
        return self.machine.trigger(*args, **kwargs)

    async def on_enter_drop(self, ev):  # noqa: ARG002
        await self.mon.drop_cb(self)

    async def re_init(self, ev):
        """
        We have an incoming packet while a DROP event is running.
        This should not happen, but whatever …
        """
        ho = ev.model.host
        mon = ho.mon
        # dprint("**RE*",ho.id)
        h = Service(mon, ho.id)
        h.data = ho.data
        # not copying the paths!
        mon.ids[h.id] = h
        await h.trigger(_E.INIT)


class HostList(CtxObj):
    """
    This class monitors the 'run.ping', 'run.id' and 'run.host' channels.
    """

    def __init__(
        self, cfg: dict, link: Link, debug: bool = False, broadcaster: Broadcaster = None
    ):
        self.link = link
        self.debug = debug
        self.cfg = cfg
        self._bc = broadcaster

        # Service Instance
        self.hsi: dict[Path, Service] = {}
        self.ids: dict[str, Service] = {}
        self.times: TimerMap[str, float] = TimerMap()

    @asynccontextmanager
    async def _ctx(self):
        if self._bc is None:
            self._bc = Broadcaster(10)

        async with self._bc, anyio.create_task_group() as self.tg:
            await self.start_tasks()
            yield self._bc
            self.tg.cancel_scope.cancel()

    async def start_tasks(self):
        "Starting Tasks. Can be supplanted by subclasses."
        self.tg.start_soon(self._mon_host)
        self.tg.start_soon(self._mon_ping)
        self.tg.start_soon(self._mon_id)
        self.tg.start_soon(self._timer)

    def set_timeout(self, host: Service, to: float | None = None):
        "Update service entry in timeout queue"
        if to is None:
            to = host.timeout
        if not to:
            with suppress(KeyError):
                self.times.pop(host.id)
            return

        # dprint("TIME ", host.id, to)
        self.times[host.id] = to

    async def _timer(self):
        async for id in self.times:
            try:
                h = self.ids[id]
            except KeyError:
                continue
            self.tg.start_soon(h.trigger, _E.TIMEOUT)

    def updated(self, host: Service, evt: EventData):
        "queue update to Broadcaster"
        if evt.transition.dest is not None or evt.kwargs.get("changed", False):
            logger.debug("Service %s: %s %s", host.id, host.state.name, srepr(host.data))
            self._bc(host)

    async def _mon_host(self):
        """
        Monitor host messages.

        These update the .hsi lookup but don't actually affect state.
        """
        async with self.link.d_watch(P("run.host"), subtree=True, state=NotGiven) as mon:
            async for p, msg in mon:
                try:
                    if msg is NotGiven:  # host deleted
                        with suppress(KeyError, AttributeError):
                            h = self.hsi.pop(p)
                            await self.drop_path(h, p)
                            if not h.data.h:
                                self.tg.start_soon(h.trigger, _E.DEL_HOST)

                        continue

                    id = msg.pop("id")

                    # points to another service? drop it from the other entry
                    with suppress(KeyError, AttributeError):
                        h = self.hsi[p]
                        if h.id != id:
                            await self.drop_path(h, p)
                            if not h.data.h:
                                self.tg.start_soon(h.trigger, _E.DEL_HOST)
                            # unconditionally updated below

                    try:
                        h = self.ids[id]
                    except KeyError:
                        self.ids[id] = h = Service(mon=self, id=id)
                        await h.trigger(_E.INIT)
                    self.hsi[p] = h
                    changed = h.data.h.get(p, None) != msg
                    self.add_path(h, p, msg)
                    self.tg.start_soon(partial(h.trigger, _E.MSG_HOST, changed=changed))
                    # dprint("H    ",p,id,h)

                except Exception as exc:
                    logger.error("BadHost %r %r", p, msg, exc_info=exc)

    async def _mon_id(self):
        async with self.link.d_watch(P("run.id"), subtree=True, meta=True, state=NotGiven) as mon:
            async for p, msg, meta in mon:
                try:
                    if len(p) != 1:
                        logger.warning("BadID %r %r", p, msg)
                        continue

                    id = p[0]
                    if msg is NotGiven:  # ID deleted
                        with suppress(KeyError):
                            h = self.ids[id]
                            self.tg.start_soon(h.trigger, _E.DEL_ID)
                        continue

                    try:
                        h = self.ids[id]
                    except KeyError:
                        self.ids[id] = h = Service(mon=self, id=id)
                        await h.trigger(_E.INIT)
                    h.last = meta.timestamp

                    changed = False
                    if h.data.get("i", None) != msg:
                        h.data.i = msg
                        changed = True
                    self.tg.start_soon(partial(h.trigger, _E.MSG_ID, changed=changed))
                    # dprint("P    ",p,msg)

                except Exception as exc:
                    logger.error("BadId %r %r", p, msg, exc_info=exc)

    async def _mon_ping(self):
        async with self.link.d_watch(P("run.ping.id"), subtree=True, state=NotGiven) as mon:
            async for p, msg in mon:
                try:
                    if len(p) != 1 or not isinstance(msg, dict):
                        logger.warning("BadPING %r %r", p, msg)
                        continue
                    id = p[0]

                    try:
                        h = self.ids[id]
                    except KeyError:
                        self.ids[id] = h = Service(mon=self, id=id)
                        await h.trigger(_E.INIT)

                    changed = False
                    if h.data.get("p", None) != msg:
                        h.data.p = msg
                        changed = True
                    self.tg.start_soon(
                        partial(
                            h.trigger, _E.MSG_PING if msg["up"] else _E.MSG_DOWN, changed=changed
                        )
                    )
                    # dprint("P    ",p,msg)

                except Exception as exc:
                    logger.error("BadPing %r %r", p, msg, exc_info=exc)

    async def drop_cb(self, host):
        """
        Called from `Service.on_enter_drop`
        """
        # dprint("  DCB",host.id)
        for p in host.data.h:
            if self.hsi.get(p, None) is host:
                del self.hsi[p]
        if self.ids.get(host.id, None) is host:
            del self.ids[host.id]
        self.set_timeout(host, False)

    async def drop_id(self, host):
        """
        Seen a message that deletes this ID entry.
        """
        pass

    def add_path(self, host: Service, path: Path, msg: dict):
        """
        Add a path with this message to the service
        """
        host.data.h[path] = msg

    async def drop_host(self, host: Service):
        """
        Seen a message that deletes this service entry.
        """
        pass

    async def drop_path(self, host: Service, path: Path):
        """
        Seen a message that deletes/supersedes this service entry.
        """
        host.data.h.pop(path, None)


class ServiceMon(HostList):
    """
    The Service Monitor runs once in a MoaT-Link network, as part of the main
    hosts's 'moat-link-host' service.

    Its main job is to remove stale retained entries under 'run.id' and 'run.host'.
    """

    def __init__(self, *a, **kw):
        """ """
        super().__init__(*a, **kw)
        self.hostdown: TimerMap[Path, float] = TimerMap()
        self.hostup: TimerMap[Path, float] = TimerMap()
        self.errored: dict[Path, bool] = dict()

    async def start_tasks(self):
        "internal helper"
        await super().start_tasks()
        self.tg.start_soon(self._mon_hostdown)
        self.tg.start_soon(self._mon_hostup)

    async def _mon_hostdown(self):
        # watch host comings+goings, complain if one is down for too long
        # (TODO: or goes down+up too often)
        async for path in self.hostdown:
            # print("******** TIME",path)
            if path in self.hsi:
                # Present. Clear error.
                await self._no_err(path)
            else:
                # not present. Error.
                await self._err(None, path, "down")

    async def _mon_hostup(self):
        # watch host.data.up
        # (TODO: or goes down+up too often)
        async for path in self.hostup:
            # print("******** TIMEUP",path)
            try:
                host = self.hsi[path]
            except KeyError:
                # not present.
                pass
            else:
                # Present. Clear error.
                if not host.data.h[path].get("up", False):
                    await self._err(None, path, "not up")

    async def drop_id(self, host):
        "Delete a host's ID message"
        await self.link.d_set(P("run.id") / host.id, retain=True)
        await super().drop_id(host)

    async def drop_host(self, host):
        "Delete a host's Service messages (yes all of them)"
        for p in host.data.h.keys():
            await self.link.d_set(P("run.host") + p, retain=True)
            self.hostdown[p] = self.cfg.timeout.restart.error
            with suppress(KeyError):
                del self.hostup[p]
        await super().drop_host(host)

    async def _err(self, host: Service | None, path: Path, msg: str, data: Any = None):
        if self.errored.get(path, "") != msg:
            dat = {"msg": msg, "level": 4}
            if data is not None:
                dat["aux"] = data
            if host is not None and (dt := host.data.h.get(path, None)) is not None:
                dat["data"] = dt
            await self.link.d_set(P("error.run.host") + path, dat)
            self.errored[path] = msg

    async def _no_err(self, path: Path):
        if self.errored.get(path, True) is not False:
            await self.link.d_set(P("error.run.host") + path)
            self.errored[path] = False

    def add_path(self, host: Service, path: Path, msg: dict):
        "Add a path with this message to the service"
        # print("******** ADD",path)
        super().add_path(host, path, msg)
        self.hostdown[path] = self.cfg.timeout.restart.flap
        if msg.get("up", False):
            with suppress(KeyError):
                del self.hostup[path]
        else:
            self.hostup[path] = self.cfg.timeout.restart.up

    async def drop_path(self, host: Service, path: Path):
        "Remove a path with this message from the service"
        # print("******** DROP",path)
        try:
            msg = host.data.h[path]
        except KeyError:
            msg = None
        try:
            self.hostdown.pop(path)
        except KeyError:
            self.hostdown[path] = self.cfg.timeout.restart.error
        else:
            await self._err(host, path, "flapping", msg)
        await super().drop_path(host, path)
