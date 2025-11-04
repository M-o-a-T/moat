from __future__ import annotations  # noqa: D100

import anyio
import logging
import time
from contextlib import asynccontextmanager, suppress
from enum import Enum, auto
from functools import partial

from attrs import define, field
from transitions_aio.extensions.factory import MachineFactory

from moat.util import CtxObj, NotGiven, P, as_service, attrdict, srepr
from moat.lib.priomap import PrioMap
from moat.util.broadcast import Broadcaster

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from transitions_aio import EventData

    from moat.util import Path
    from moat.link.client import Link

    from collections.abc import Awaitable
    from typing import NoReturn

__all__ = ["HostMon", "cmd_host"]

logger = logging.getLogger(__name__)

# def dprint(*a):
#     print(f"{int(time.monotonic()) % 1000 :03d}", *a)


async def cmd_host(link: Link, cfg: dict, main: bool = False, *, debug=False) -> NoReturn:
    """
    Host specific runner.

    This is the handler for the "moat-link-host" service.
    It tells MoaT-Link that a particular host is up.
    """

    async with as_service(attrdict(debug=debug, link=link)) as srv:
        if main:
            await srv.tg.start(HostMon(cfg=cfg, link=link, debug=debug).run)

        srv.started()
        await anyio.sleep_forever()


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
    DEL_HOST = auto()  # Host gets dropped, or replaced
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
            dict(name=_S.DROP),
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
            dict(trigger=_E.DEL_ID, source=_S.DROP, dest=None),
            dict(trigger=_E.TIMEOUT, source=_S.DROP, dest=None),
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
        )
        self.host = host

    def _set_timeout(self, ed: EventData):
        host = ed.model.host
        host.mon.set_timeout(host)


@define(eq=False)
class Host:
    """Contains data for one particular host, service, or instance."""

    mon = field()
    id = field()
    path = field(default=())

    # These get filled via path
    host = field(type=str, default=None, init=False)
    service = field(type=str, default=None, init=False)
    instance = field(type=str, default=None, init=False)

    data = field(factory=attrdict, init=False)
    machine = field(default=None, init=False)

    _last = field(default=0, init=False)

    def __attrs_post_init__(self):
        p = self.path
        with suppress(IndexError):
            self.host = p[0]
            self.service = p[1]
            self.instance = p[2]
        self.machine = HostMachine(self)

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
        elif self.state in (HostState.DOWN,) or self.state in (HostState.STALE,):
            val = "delete"
        else:
            val = "timeout"
        res = self.mon.cfg.timeout.ping[val]
        if self.last:
            age = time.time() - self.last
            res = min(res, max(self.mon.cfg.timeout.ping.min, age))
        return res

    def updated(self, evt):
        self.mon.updated(self, evt)

    def drop_id(self) -> Awaitable[None]:
        return self.mon.drop_id(self)

    def drop_host(self) -> Awaitable[None]:
        return self.mon.drop_host(self)

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
        h = Host(mon, ho.id, ho.path)
        h.data = ho.data
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

        self._retime = anyio.Event()

        # Host Service Instance
        self.hsi: dict[Path, Host] = {}
        self.ids: dict[str, Host] = {}
        self.times: PrioMap[str, float] = PrioMap()

    @asynccontextmanager
    async def _ctx(self):
        if self._bc is None:
            self._bc = Broadcaster(10)

        async with self._bc, anyio.create_task_group() as self.tg:
            self.tg.start_soon(self._mon_host)
            self.tg.start_soon(self._mon_ping)
            self.tg.start_soon(self._mon_id)
            self.tg.start_soon(self._timer)
            yield self._bc
            self.tg.cancel_scope.cancel()

    def set_timeout(self, host, to=None):
        if to is None:
            to = host.timeout
        if not to:
            self.times.pop(host.id, None)
            return

        tm = time.monotonic() + to

        if len(self.times) and self.times.peek()[1] > tm:
            self._retime.set()
        # dprint("TIME ",host.id,tm-time.monotonic())
        self.times[host.id] = tm

    async def _timer(self):
        async for id, timeout in self.times:
            h = self.ids[id]

            t = time.monotonic()
            if t < timeout:
                self.times[id] = timeout
                # dprint("WAIT+",id,timeout-t)
                with anyio.move_on_after(timeout - t):
                    await self._retime.wait()
                    self._retime = anyio.Event()
                continue

            # dprint("OUT  ",h.id)
            self.tg.start_soon(h.trigger, _E.TIMEOUT)

    def updated(self, host: Host, evt: EventData):
        if evt.transition.dest is not None or evt.kwargs.get("changed", False):
            logger.debug("Host %s: %s %s", host.id, host.state.name, srepr(host.data))
            self._bc(host)

    async def _mon_host(self):
        """
        Monitor host messages.

        These update the .hsi lookup but don't actually affect state.
        """
        async with self.link.d_watch(
            P("run.host"), subtree=True, meta=True, state=NotGiven
        ) as mon:
            async for p, msg, meta in mon:
                try:
                    if msg is NotGiven:  # host deleted
                        with suppress(KeyError, AttributeError):
                            h = self.hsi.pop(p)
                            del h.data.h
                        continue

                    id = msg["id"]

                    # now points to another host? drop it from the other entry
                    with suppress(KeyError, AttributeError):
                        h = self.hsi[p]
                        if h.id != id:
                            del self.ids[h.id].data.h
                            # unconditionally updated below

                    try:
                        h = self.ids[id]
                    except KeyError:
                        self.ids[id] = h = Host(mon=self, id=id, path=p)
                        await h.trigger(_E.INIT)
                        self.hsi[p] = h
                    else:
                        if h.path != p:
                            if len(h.path):
                                self.hsi.pop(h.path, None)
                            h.path = p
                            self.hsi[p] = h.path
                    h.last = meta.timestamp
                    h.data.h = msg
                    self.tg.start_soon(h.trigger, _E.MSG_HOST)

                    changed = False
                    if h.data.get("h", None) != msg:
                        h.data.h = msg
                        changed = True
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
                        self.ids[id] = h = Host(mon=self, id=id)
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
                        self.ids[id] = h = Host(mon=self, id=id)
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
        Called from `Host.on_enter_drop`
        """
        # dprint("  DCB",host.id)
        if self.hsi.get(host.path, None) is host:
            del self.hsi[host.path]
        if self.ids.get(host.id, None) is host:
            del self.ids[host.id]
        self.set_timeout(host, False)

    async def drop_id(self, host):
        """
        Send a message to delete this ID entry.
        """
        pass

    async def drop_host(self, host):
        """
        Send a message to delete this host entry.
        """
        pass


class HostMon(HostList):
    """
    The Host Monitor runs once in a MoaT-Link network, as part of the main
    hosts's 'moat-link-host' service.

    Its main job is to remove stale retained entries under 'run.id' and 'run.host'.
    """

    async def drop_id(self, host):
        """
        Send a message to delete this ID entry.
        """
        if "h" in host.data:
            await self.link.d_set(P("run.id") / host.id, retain=True)
        await super().drop_id(host)

    async def drop_host(self, host):
        """
        Send a message to delete this host entry.
        """
        await self.link.d_set(P("run.host") + host.path, retain=True)
        await super().drop_host(host)
