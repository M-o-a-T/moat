# Local server
from __future__ import annotations

import anyio
import io
import os
import signal
import time
from anyio.abc import SocketAttribute

from attrs import define, field
from asyncscope import scope
from datetime import datetime, UTC
from collections import defaultdict

from moat.lib.cmd import CmdHandler
from moat.lib.cmd.anyio import run as run_cmd_anyio
from moat.link.auth import AnonAuth, TokenAuth
from moat.link.conn import SubConn, CmdCommon
from moat.link.client import BasicLink
from moat.link.backend import get_backend
from moat.link.exceptions import ClientError
from moat.link.meta import MsgMeta
from moat.util.cbor import StdCBOR, CBOR_TAG_MOAT_FILE_ID, CBOR_TAG_MOAT_FILE_END,CBOR_TAG_MOAT_CHANGE
from moat.lib.codec.cbor import Tag as CBORTag, CBOR_TAG_CBOR_FILEHEADER

from mqttproto import QoS

try:
    from contextlib import asynccontextmanager
except ImportError:
    from async_generator import asynccontextmanager

import logging
from functools import partial

from asyncactor import (
    Actor,
    DetagEvent,
    GoodNodeEvent,
    RawMsgEvent,
    RecoverEvent,
    TagEvent,
    UntagEvent,
)
from asyncactor.backend import get_transport
from range_set import RangeSet

from moat.util import (
    attrdict,
    to_attrdict,
    combine_dict,
    CtxObj,
    gen_ident,
    gen_ssl,
    MsgReader,
    MsgWriter,
    NotGiven,
    P,
    Path,
    PathLongener,
    PathShortener,
    run_tcp_server,
    ValueEvent,
    Root,
)

from moat.util.broadcast import Broadcaster

# from . import _version_tuple
# from . import client as moat_kv_client  # needs to be mock-able
# from .actor.deletor import DeleteActor
# from .codec import packer, stream_unpacker, unpacker
# from .exceptions import (
#    ACLError,
#    CancelledError,
#    ClientChainError,
#    ClientError,
#    NoAuthError,
#    ServerClosedError,
#    ServerConnectionError,
#    ServerError,
# )
from moat.link.node import Node
from moat.link.hello import Hello

from typing import Any, TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Never

# from .types import ACLFinder, ACLStepper, ConvNull, NullACL, RootEntry


class BadFile(ValueError):
    pass


@asynccontextmanager
async def EventSetter(evt):
    try:
        yield
    finally:
        evt.set()


Stream = anyio.abc.ByteStream

ClosedResourceError = anyio.ClosedResourceError

_client_nr = 0


class AuthError(RuntimeError):
    pass


def max_n(a, b):
    if a is None:
        return b
    elif b is None:
        return a
    elif a < b:
        return b
    else:
        return a


def cmp_n(a, b):
    if a is None:
        a = -1
    if b is None:
        b = -1
    return b - a


class HelloProc:
    """
    A hacked-up command processor for receiving the first client message.
    """

    def __init__(self, client):
        self.client = client

    async def received(self, msg):
        qlen = msg.get("qlen", 0)
        self.client.qlen = min(qlen, self.client.server.cfg.server.buffer)
        del self.client.in_stream[0]

    async def aclose(self):
        self.client.in_stream.pop(0, None)


class ServerClient(SubConn, CmdCommon):
    """Represent one (non-server) client."""

    _hello: Hello | None = None
    _auth_data: Any = None

    def __init__(self, server: Server, name: str, stream: Stream):
        self.server = server
        self.name = name
        self.stream = stream

        global _client_nr
        _client_nr += 1
        self.client_nr = _client_nr

        self.logger = logging.getLogger(f"moat.link.server.{name}.{self.client_nr}")

    async def run(self):
        """Main loop for this client connection."""

        self.logger.debug("START %s C_%d", self.name, self.client_nr)
        self._handler = cmd = CmdHandler(self._cmd_in)
        self._hello = Hello(
            self,
            them=f"C_{self.client_nr}",
            auth_in=[TokenAuth("Duh"), AnonAuth()],
        )
        async with (
            anyio.create_task_group() as self.tg,
            run_cmd_anyio(cmd, self.stream),
        ):
            # basic setup
            try:
                if await self._hello.run() is False or not (auth := self._hello.auth_data):
                    self.logger.debug("NO %s", self.client_nr)
                    return
            finally:
                del self._hello
            self._auth_data = auth

            # periodic ping
            while True:
                # XXX configurable; only when idle
                await anyio.sleep(30)
                with anyio.fail_after(self.server.cfg.server.ping_timeout):
                    await cmd.cmd(P("i.ping"))

    @property
    def auth_data(self):
        """
        Retrieve auth data.

        These might be stored in the Hello processor while startup is incomplete.
        """
        if self._hello is not None:
            return self._hello.auth_data
        return self._auth_data

    def _cmd_in(self, msg) -> Awaitable:
        """
        Process an incoming message.
        """
        self.logger.debug("IN %s", msg)
        if self._hello is not None and self._hello.auth_data is None:
            return self._hello.cmd_in(msg)
        cmd = getattr(self, "cmd_" + "_".join(msg.cmd))
        return cmd(msg)

    async def cmd_d_get(self, msg):
        """Get the data of a sub-node.

        Arguments:
        * path

        Result:
        * data
        * metadata
        """
        d = self.server.data[msg[0]]
        await msg.result(d.data, d.meta)


    async def cmd_d_list(self, msg):
        """Get the child names of a sub-node.
        Arguments:
        * path

        Stream:
        * strings
        """

        async with msg.stream_w():
            for k in list(self.server.data[msg[1]].keys()):
                await msg.send(k)

    async def cmd_d_walk(self, msg):
        """
        Get a whole subtree.
        Arguments:
        * pathname
        * min timestamp
        * min depth
        * max depth
        """

        ps = PathShortener()

        async def _writer(p, n):
            d, sp = ps.short(p)
            await msg.send(d, sp, n.data, *n.meta.dump())

        d = self.server.data.get(msg[0], create=False)
        ts = msg.get(1, 0)
        xmin = msg.get(2, 0)
        xmax = msg.get(3, -1)
        async with msg.stream_w():
            await d.walk(_writer, timestamp=ts, min_depth=xmin, max_depth=xmax)

    async def cmd_d_set(self, msg, **kw):
        """Set a node's value.
        Arguments:
        * pathname
        * value
        * optional: metadata

        You should not call this. Send to the MQTT topic directly.
        """
        path = msg[0]
        value = msg[1]
        if len(msg) > 2:
            meta = msg[2]
        else:
            meta = MsgMeta(origin=self.name)
        meta.source="Client"

        self.server.maybe_update(path,value,meta)

    async def cmd_d_del(self, msg, **kw):
        """Delete a node's value."""
        return await self._set_value(msg, **kw)

    async def cmd_d_update(self, msg):
        """
        Apply a stored update.

        You usually do this via a stream command.
        """
        msg = UpdateEvent.deserialize(
            self.root,
            msg,
            nulls_ok=self.nulls_ok,
            conv=self.conv,
            cache=self.server._nodes,
        )
        res = await msg.entry.apply(msg, server=self, root=self.root)
        if res is None:
            return False
        else:
            return res.serialize(chop_path=self._chop_path, conv=self.conv)

    async def cmd_d_chkdel(self, msg):
        nodes = msg.nodes
        deleted = NodeSet()
        for n, v in nodes.items():
            n = Node(n, None, cache=self.server.node_cache)
            r = RangeSet()
            r.__setstate__(v)
            for a, b in r:
                for t in range(a, b):
                    if t not in n:
                        deleted.add(n.name, t)
        if deleted:
            await self.server._send_event("info", attrdict(deleted=deleted.serialize()))

    async def cmd_i_state(self, msg):
        """Return some info about this node's internal state"""
        return await self.server.get_state(**msg)

    async def cmd_d_deltree(self, msg):
        """Delete a node's value.
        Sub-nodes are cleared (after their parent).
        """
        seq = msg.seq
        if not msg.path:
            raise ClientError("You can't delete the root node")
        ps = PathShortener(msg.path)

        async def _del(entry, acl):
            res = 0
            if entry.data is not None:
                async with self.server.next_event() as event:
                    evt = await entry.set_data(event, NotGiven, server=self, tock=self.server.tock)
                    if nchain:
                        r = evt.serialize(
                            chop_path=self._chop_path,
                            nchain=nchain,
                            with_old=True,
                            conv=self.conv,
                        )
                        r["seq"] = seq
                        r.pop("new_value", None)  # always None
                        ps(r)
                        await self.send(r)
                res += 1
            if not acl.allows("e") or not acl.allows("x"):
                return
            for v in entry.values():
                a = acl.step(v, new=True)
                res += await _del(v, a)
            return res

        res = await _del(entry, acl)
        if nchain:
            await self.send({"seq": seq, "state": "end"})
        else:
            return {"changed": res}

    async def cmd_i_log(self, msg):
        await self.server.run_saver(path=msg["path"], save_state=msg.get("fetch", False))
        return True

    async def cmd_s_save(self, msg):
        prefix = msg.get("prefix",P(":"))
        await self.server.save(path=msg["path"], prefix=prefix)

        return True

    async def cmd_s_load(self, msg):
        prefix = msg.get("prefix",P(":"))
        return await self.server.load(path=msg["path"], prefix=prefix)

    async def cmd_i_stop(self, msg):
        try:
            t = self.tasks[msg.task]
        except KeyError:
            return False
        t.cancel()
        return True

    def drop_old_event(self, evt, old_evt=NotGiven):
        return self.server.drop_old_event(evt, old_evt)

    def mark_deleted(self, node, tick):
        return self.server.mark_deleted(node, tick)


class _RecoverControl:
    _id = 0

    def __init__(
        self,
        server,
        scope,
        prio,
        local_history,
        sources,  # pylint:disable=redefined-outer-name
    ):
        self.server = server
        self.scope = scope
        self.prio = prio

        local_history = set(local_history)
        sources = set(sources)
        self.local_history = local_history - sources
        self.sources = sources - local_history
        self.tock = server.tock
        type(self)._id += 1
        self._id = type(self)._id

        self._waiters = {}

    async def _start(self):
        chk = set()
        rt = self.server._recover_tasks
        for node in self.local_history:
            xrc = rt.get(node, None)
            if xrc is not None:
                chk.add(xrc)
            self.server._recover_tasks[node] = self
        for t in chk:
            await t._check()

    async def _check(self):
        lh = []
        rt = self.server._recover_tasks
        for n in self.local_history:
            if rt.get(n, None) is self:
                lh.append(n)
            self.local_history = lh
            if not lh:
                self.cancel()

    def __hash__(self):
        return id(self)

    def cancel(self):
        self.scope.cancel()
        rt = self.server._recover_tasks
        for node in self.local_history:
            if rt.get(node, None) is self:
                del rt[node]
        self.local_history = ()
        for evt in list(self._waiters.values()):
            evt.set()

    def set(self, n):
        evt = self._waiters.get(n, None)
        if evt is None:
            evt = anyio.Event()
            self._waiters[n] = evt
        evt.set()

    async def wait(self, n):
        evt = self._waiters.get(n, None)
        if evt is None:
            evt = anyio.Event()
            self._waiters[n] = evt
        await evt.wait()


class Server:
    """
    This is the main MoaT-Link server. It manages connections to the MQTT server,
    the clients, and (optionally) logs all changes to a file.

    Args:
      name (str): the name of this MoaT-KV server instance.
        It **must** be unique.
      cfg: configuration.
        See ``_cfg.yaml`` for default values.
        The relevant part is the ``link.server`` sub-dict (mostly).
      init (Any):
        The initial content of the root entry. **Do not use this**, except
          when setting up an entirely new MoaT-KV network.

    """

    # pylint: disable=no-member # mis-categorizing cfg as tuple
    data: Node
    name: str
    backend: Link

    cfg: attrdict

    service_monitor: Broadcaster[Message[ServerData]]
    write_monitor: Broadcaster[tuple[Any, MsgMeta, int | float]]

    logger: logging.Logger

    last_auth: str | None = None
    cur_auth: str = None

    _writing: set[str]
    _writing_done: anyio.Event
    _stopped: anyio.Event = None

    def __init__(self, cfg: dict, name: str, init: Any = NotGiven):
        self.data = Node()
        self.name = name
        self.cfg = cfg

        if init is not NotGiven:
            self.data.set(Path(), init, MsgMeta(origin="INIT"))

        self.logger = logging.getLogger("moat.link.server." + name)
        self._writing = set()
        self._writing_done = anyio.Event()

        # connected clients
        self._clients: set[ServerClient] = set()

    def refresh_auth(self):
        """
        Generate a new access token (but remember the previous one)
        """
        self.last_auth = self.cur_auth
        self.cur_auth = gen_ident(20)

    @property
    def tokens(self):
        res = [self.cur_auth]
        if self.last_auth is not None:
            res.append(self.last_auth)
        return res


    def maybe_update(self, path, data, meta):
        """
        A data item arrives.

        Update our store if it's newer.
        """
        if not self.data.set(path,data,meta):
            return False
        self.write_monitor((path, data, meta))
        return True


    async def _backend_monitor(self, task_status: anyio.abc.TaskStatus = anyio.TASK_STATUS_IGNORED):
        """
        The task that listens to the backend's message stream and updates
        the data store.
        """
        chop = len(self.cfg.root)
        async with self.backend.monitor(P(":R.#"), raw=False, qos=QoS.AT_LEAST_ONCE, no_local=True) as stream:
            task_status.started()
            async for msg in stream:
                self.logger.debug("Recv: %r", msg)
                topic = msg.topic[chop:]
                if topic and topic[0] == "run":
                    continue

                msg.meta.source="Mon"
                self.maybe_update(Path.build(topic), msg.data, msg.meta)

    async def _backend_sender(self, task_status: anyio.abc.TaskStatus = anyio.TASK_STATUS_IGNORED):
        rdr = self.write_monitor.reader(999)
        task_status.started()
        async for msg in rdr:
            if isinstance(msg,CBORTag):
                continue
            p,d,m = msg
            if m.source == "Mon" or m.source[0] == "_":
                continue
            await self.backend.send(topic=P(":R")+p, payload=d, meta=m)


    async def _pinger(
        self,
        ready: anyio.Event,
        *,
        task_status: anyio.abc.TaskStatus = anyio.TASK_STATUS_IGNORED,
    ):
        """
        This task
        * sends PING messages
        * handles incoming pings
        * triggers split recovery

        The initial ping is delayed randomly.

        Args:
          delay: an event to set after the initial ping message has been
            sent.
        """
        T = get_transport("moat_link")
        async with Actor(
            T(self.backend, P(":R.run.service.ping.main")),
            name=self.name,
            cfg=self.cfg.server.ping,
            send_raw=True,
        ) as actor:
            self._actor = actor
            task_status.started()

            async for msg in actor:
                self.logger.debug("ACT IN %r", msg)

                if isinstance(msg, RecoverEvent):
                    await self.spawn(
                        self.recover_split,
                        msg.prio,
                        msg.replace,
                        msg.local_nodes,
                        msg.remote_nodes,
                    )

                elif isinstance(msg, GoodNodeEvent):
                    await self.spawn(self.fetch_data, msg.nodes)
                    ready.set()

                elif isinstance(msg, RawMsgEvent):
                    msg = msg.msg
                    msg_node = msg.get("node", None)
                    if msg_node is None:
                        msg_node = msg.get("history", (None,))[0]
                        if msg_node is None:
                            continue
                    val = msg.get("value", None)
                    tock = None
                    if val is not None:
                        tock, val = val
                        await self.tock_seen(tock)
                    # node = Node(msg_node, val, cache=self.node_cache)
                    # if tock is not None:
                    #    node.tock = tock

                elif isinstance(msg, TagEvent):
                    # We're "it"; find missing data
                    # await self._send_missing()
                    await self.set_main_link()

                elif isinstance(msg, (UntagEvent, DetagEvent)):
                    pass

    async def set_main_link(self):
        await self.backend.send(
            P(":R.run.service.main"),
            {"link": self.link_data, "auth": {"token": self.cur_auth}},
            meta=MsgMeta(origin=self.name),
            retain=True,
        )

    async def _get_host_port(self, host):
        """Retrieve the remote system to connect to.

        WARNING: While this is nice, there'a chicken-and-egg problem here.
        While you can use the hostmap to temporarily add new hosts with
        unusual addresses, the new host still needs a config entry.
        """

        # this is async because the test mock needs that

        port = self.cfg.conn.port
        domain = self.cfg.domain
        try:
            # First try to read the host name from the meta-root's
            # "hostmap" entry, if any.
            hme = self.root.follow(Path(None, "hostmap", host), create=False, nulls_ok=True)
            if hme.data is NotGiven:
                raise KeyError(host)
        except KeyError:
            hostmap = self.cfg.hostmap
            if host in hostmap:
                host = hostmap[host]
                if not isinstance(host, str):
                    # must be a 2-element tuple
                    host, port = host
                else:
                    # If it's a string, the port may have been passed as
                    # part of the hostname. (Notably on the command line.)
                    try:
                        host, port = host.rsplit(":", 1)
                    except ValueError:
                        pass
                    else:
                        port = int(port)
        else:
            # The hostmap entry in the database must be a tuple
            host, port = hme.data

        if domain is not None and "." not in host and host != "localhost":
            host += "." + domain
        return (host, port)

    async def do_send_missing(self):
        """Task to periodically send "missing …" messages"""
        self.logger.debug("send-missing started")
        clock = self.cfg.server.ping.gap
        while self.fetch_missing:
            if self.fetch_running is not False:
                self.logger.debug("send-missing halted")
                return
            clock *= self._actor.random / 2 + 1
            await anyio.sleep(clock)

            n = 0
            msg = dict()
            for n in list(self.fetch_missing):
                m = n.local_missing
                nl = len(m)
                if nl == 0:
                    self.fetch_missing.remove(n)
                    continue

                mr = self.seen_missing.get(n.name, None)
                if mr is not None:
                    m -= mr
                if len(m) == 0:
                    continue
                msg[n.name] = m.__getstate__()
            self.seen_missing = {}
            if not n:  # nothing more to do
                break
            if not len(msg):  # others already did the work, this time
                continue
            msg = attrdict(missing=msg)
            self.logger.warning("Missing data: %r", msg)
            await self._send_event("info", msg)

        self.logger.debug("send-missing ended")
        if self.node.tick is None:
            self.node.tick = 0
            await self._check_ticked()
        self.fetch_running = None

    async def fetch_data(self, nodes, authoritative=False):
        """
        We are newly started and don't have any data.

        Try to get the initial data from some other node.
        """
        if self.fetch_running is not None:
            return
        self.fetch_running = True
        for n in nodes:
            try:
                host, port = await self._get_host_port(n)
                cfg = combine_dict(
                    {"host": host, "port": port, "name": self.node.name},
                    self.cfg.conn,
                    cls=attrdict,
                )
                auth = cfg.get("auth", None)
                from .auth import gen_auth

                cfg["auth"] = gen_auth(auth)

                self.logger.info("Sync: connecting: %s", cfg)
                async with scope.using_scope(f"moat.kv.sync.{self.node.name}"):
                    client = await moat_kv_client.client_scope(conn=cfg)
                    # TODO auth this client

                    pl = PathLongener(())
                    res = await client._request(
                        "get_tree",
                        iter=True,
                        from_server=self.node.name,
                        nchain=-1,
                        path=(),
                    )
                    async for r in res:
                        pl(r)
                        r = UpdateEvent.deserialize(
                            self.root,
                            r,
                            cache=self.node_cache,
                            nulls_ok=True,
                        )
                        await r.entry.apply(r, server=self, root=self.paranoid_root)
                    await self.tock_seen(res.end_msg.tock)

                    pl = PathLongener((None,))
                    res = await client._request(
                        "get_tree_internal",
                        iter=True,
                        from_server=self.node.name,
                        nchain=-1,
                        path=(),
                    )
                    async for r in res:
                        pl(r)
                        r = UpdateEvent.deserialize(
                            self.root,
                            r,
                            cache=self.node_cache,
                            nulls_ok=True,
                        )
                        await r.entry.apply(r, server=self, root=self.paranoid_root)
                    await self.tock_seen(res.end_msg.tock)

                    res = await client._request(
                        "get_state",
                        nodes=True,
                        from_server=self.node.name,
                        known=True,
                        deleted=True,
                        iter=False,
                    )
                    await self._process_info(res)

            except (AttributeError, KeyError, ValueError, AssertionError, TypeError):
                raise
            except Exception:
                self.logger.exception("Unable to connect to %s:%d", host, port)
            else:
                # At this point we successfully cloned some other
                # node's state, so we now need to find whatever that
                # node didn't have.

                for nst in self._nodes.values():
                    if nst.tick and len(nst.local_missing):
                        self.fetch_missing.add(nst)
                if len(self.fetch_missing):
                    self.fetch_running = False
                    for nm in self.fetch_missing:
                        self.logger.error("Sync: missing: %s %s", nm.name, nm.local_missing)
                    await self.spawn(self.do_send_missing)
                if self.force_startup or not len(self.fetch_missing):
                    if self.node.tick is None:
                        self.node.tick = 0
                    self.fetch_running = None
                    await self._check_ticked()
                return

        self.fetch_running = None

    async def _process_info(self, msg):
        """
        Process "info" messages.
        """
        await self.tock_seen(msg.get("tock", 0))

        # nodes: list of known nodes and their max ticks
        for nn, t in msg.get("nodes", {}).items():
            nn = Node(nn, cache=self.node_cache)
            nn.tick = max_n(nn.tick, t)

        # known: per-node range of ticks that have been resolved
        for nn, k in msg.get("known", {}).items():
            nn = Node(nn, cache=self.node_cache)
            r = RangeSet()
            r.__setstate__(k)
            nn.report_superseded(r, local=True)

        # deleted: per-node range of ticks that have been deleted
        deleted = msg.get("deleted", {})
        for nn, k in deleted.items():
            nn = Node(nn, cache=self.node_cache)
            r = RangeSet()
            r.__setstate__(k)
            nn.report_deleted(r, self)

        # remote_missing: per-node range of ticks that should be re-sent
        # This is used when loading data from a state file
        for nn, k in msg.get("remote_missing", {}).items():
            nn = Node(nn, cache=self.node_cache)
            r = RangeSet()
            r.__setstate__(k)
            nn.report_missing(r)

        # Dropped nodes.
        for nn in msg.get("node_drop", ()):
            self._dropped_node(nn)

    async def drop_node(self, name):
        self._dropped_node(name)
        await self._send_event("info", attrdict(node_drop=[name]))

    def _dropped_node(self, name):
        try:
            nn = Node(name, cache=self.node_cache, create=False)
        except KeyError:
            return
        for _ in nn.enumerate(current=True):
            break
        else:  # no item found
            nn.kill_this_node(self.node_cache)

    async def _check_ticked(self):
        if self._ready is None:
            return
        if self.node.tick is not None:
            self.logger.debug("Ready")
            self._ready.set()
            await self._set_tock()
        else:
            # self.logger.debug("Not yet ready.")
            pass

    async def recover_split(self, prio, replace, local_history, sources):
        """
        Recover from a network split.
        """
        with anyio.CancelScope() as cs:
            for node in sources:
                if node not in self._recover_tasks:
                    break
            else:
                return
            t = _RecoverControl(self, cs, prio, local_history, sources)
            self.logger.debug(
                "SplitRecover %d: start %d %s local=%r remote=%r",
                t._id,
                prio,
                replace,
                local_history,
                sources,
            )
            try:
                await t._start()
                clock = self.cfg.server.ping.cycle

                # Step 1: send an info/ticks message
                # for prio=0 this fires immediately. That's intentional.
                with anyio.move_on_after(clock * (1 - 1 / (1 << prio))) as x:
                    await t.wait(1)
                if x.cancel_called:
                    msg = dict((x.name, x.tick) for x in self._nodes.values())

                    msg = attrdict(ticks=msg)
                    if self.node_drop:
                        msg.node_drop = list(self.node_drop)
                    await self._send_event("info", msg)

                # Step 2: send an info/missing message
                # for prio=0 this fires after clock/2, so that we get a
                # chance to wait for other info/ticks messages. We can't
                # trigger on them because there may be more than one, for a
                # n-way merge.
                with anyio.move_on_after(clock * (2 - 1 / (1 << prio)) / 2) as x:
                    await t.wait(2)

                if x.cancel_called:
                    await self._send_missing(force=True)

                # wait a bit more before continuing. Again this depends on
                # `prio` so that there won't be two nodes that send the same
                # data at the same time, hopefully.
                await anyio.sleep(clock * (1 - 1 / (1 << prio)))

                # Step 3: start a task that sends stuff
                await self._run_send_missing(prio)

            finally:
                with anyio.CancelScope(shield=True):
                    # Protect against cleaning up when another recovery task has
                    # been started (because we saw another merge)
                    self.logger.debug("SplitRecover %d: finished @%d", t._id, t.tock)
                    self.seen_missing = {}
                    t.cancel()

    async def _send_missing(self, force=False):
        msg = dict()
        for n in list(self._nodes.values()):
            if not n.tick:
                continue
            m = n.local_missing
            mr = self.seen_missing.get(n.name, None)
            if mr is not None:
                m -= mr
            if len(m) == 0:
                continue
            msg[n.name] = m.__getstate__()
            if mr is None:
                self.seen_missing[n.name] = m
            else:
                mr += m

        if force or msg:
            msg = attrdict(missing=msg)
            if self.node_drop:
                msg.node_drop = list(self.node_drop)
            await self._send_event("info", msg)

    async def _run_send_missing(self, prio):
        """Start :meth:`_send_missing_data` if it's not running"""

        if self.sending_missing is None:
            self.sending_missing = True
            await self.spawn(self._send_missing_data, prio)
        elif not self.sending_missing:
            self.sending_missing = True

    async def _send_missing_data(self, prio):
        """Step 3 of the re-join protocol.
        For each node, collect events that somebody has reported as missing,
        and re-broadcast them. If the event is unavailable, send a "known"
        / "deleted" message.
        """

        self.logger.debug("SendMissing %s", prio)
        clock = self.cfg.server.ping.cycle
        if prio is None:
            await anyio.sleep(clock * (1 + self._actor.random / 3))
        else:
            await anyio.sleep(clock * (1 - (1 / (1 << prio)) / 2 - self._actor.random / 5))

        self.logger.debug("SendMissingGo %s %s", prio, self.sending_missing)
        while self.sending_missing:
            self.sending_missing = False
            nodes = list(self._nodes.values())
            self._actor._rand.shuffle(nodes)
            known = {}
            deleted = {}
            for n in nodes:
                self.logger.debug(
                    "SendMissingGo %s %r %r",
                    n.name,
                    n.remote_missing,
                    n.local_superseded,
                )
                k = n.remote_missing & n.local_superseded
                for r in n.remote_missing & n.local_present:
                    for t in range(*r):
                        if t not in n.remote_missing:
                            # some other node could have sent this while we worked
                            await anyio.sleep(self.cfg.server.ping.gap / 3)
                            continue
                        if t in n:
                            # could have been deleted while sleeping
                            msg = n[t].serialize()
                            await self._send_event("update", msg)
                            n.remote_missing.discard(t)
                if k:
                    known[n.name] = k.__getstate__()

                d = n.remote_missing & n.local_deleted
                if d:
                    deleted[n.name] = d.__getstate__()

            msg = attrdict()
            if known:
                msg.known = known
            if deleted:
                msg.deleted = deleted
            if self.node_drop:
                msg.node_drop = list(self.node_drop)
            if msg:
                await self._send_event("info", attrdict(known=known, deleted=deleted))
        self.sending_missing = None

    async def load(
        self,
        path: str = None,
        stream: io.IOBase = None,
        local: bool = False,
        prefix: Path=P(":"),
        authoritative: bool = False,
    ):
        """Load data from this stream

        Args:
          ``fd``: The stream to read.
          ``local``: Flag whether this file contains initial data and thus
                     its contents shall not be broadcast. Don't set this if
                     the server is already operational.
        """
        longer = PathLongener(())

        upd,skp,met = 0,0,[]

        async with MsgReader(path=path, stream=stream, codec="std-cbor") as rdr:
            async for m in rdr:
                if isinstance(m,CBORTag) and m.tag == CBOR_TAG_CBOR_FILEHEADER:
                    m = m.value
                if isinstance(m,CBORTag):
                    met.append(m)
                    continue
                d,p,data,*mt = m
                path = longer.long(d,p)
                meta = MsgMeta.restore(mt)
                meta.source=str(path)
                if self.maybe_update(prefix+path,data,meta):
                    upd += 1
                else:
                    skp += 1

        self.logger.debug("Loading finished.")
        return (upd,skp,met)


    async def _save(self, writer:Callable, shorter:PathShortener, hdr:bool|CBORTag=True, ftr:bool|CBORTag=True, prefix=P(":"),**kw):
        """Save the current state."""
        async def saver(path, data):
            if data.data is NotGiven and data.meta is None:
                return
            d,p = shorter.short(path)
            await writer([d,p,data.data,*data.meta.dump()])


        if hdr:
            if hdr is True:
                kw["state"] = self.get_state()
                hdr = self.gen_hdr_start(**kw)
            await writer(hdr)

        # await writer({"info": msg})
        await self.data[prefix].walk(saver, timestamp=kw.get("timestamp",0))

        if ftr:
            if ftr is True:
                ftr = self.gen_hdr_stop()
            await writer(ftr)


    def gen_hdr_start(self, name, mode="full", **kw):
        """Return the CBOR tag for a start-of-file record"""
        from moat.util.cbor import gen_start
        fn=anyio.Path(name).name
        mstr = f"MoaT-Link {mode} {fn !r}"
        mstr += " "*(25-len(mstr))
        kw["mode"] = mode
        kw["name"] = name

        return gen_start(mstr,**kw)

    def gen_hdr_stop(self, **kw):
        """Return the CBOR tag for an end-of-file record"""
        from moat.util.cbor import gen_stop

        return gen_stop(**kw)
    
    def gen_hdr_change(self, **kw):
        """Return the CBOR tag that describes a change"""
        from moat.util.cbor import gen_change

        return gen_change(**kw)
    

    def get_state(self):
        return dict()


    async def save(self, path: str = None, **kw):
        """Save the current state to ``path``."""
        shorter = PathShortener([])
        try:
            self._writing.add(str(path))
            async with MsgWriter(path=path, codec="std-cbor") as mw:
                await self._save(mw, shorter, name=path, **kw)
        finally:
            self._writing.remove(str(path))

    async def save_stream(
        self,
        path: str = None,
        save_state: bool = False,
        task_status= anyio.TASK_STATUS_IGNORED,
    ):
        """Save the current state to ``path``.
        Continue writing updates until cancelled.

        Args:
          path: The file to save to.
          save_state: Flag whether to write the current state.
            If ``False`` (the default), only write changes.

        This task flushes the current buffer to disk when five seconds
        pass without updates, or every 100 messages.
        """
        shorter = PathShortener([])

        with anyio.CancelScope() as scope:
            try:
                self._writing.add(str(path))
                rdr = self.write_monitor.reader(999)
                async with (
                        anyio.create_task_group() as tg,
                        MsgWriter(path=path, codec="std-cbor") as mw,
                        ):
                    try:
                        msg = self.gen_hdr_start(name=str(path), mode="full" if save_state else "incr", state=None if save_state else False)
                        await mw(msg)

                        msg = self.gen_hdr_stop(name=str(path), mode="restart" if save_state else "next")
                        self.write_monitor(msg)
                        task_status.started(scope)

                        if save_state:
                            tg.start_soon(partial(self._save, mw, shorter, hdr=False,ftr=self.gen_hdr_change(state=False)))


                        await self._save_stream(rdr,mw, shorter, msg)
                    except BaseException as exc:
                        # 
                        with anyio.move_on_after(2, shield=True):
                            await mw(self.gen_hdr_stop(mode="error", error=repr(exc)))
                        raise

                    finally:
                        with anyio.move_on_after(2, shield=True):
                            await mw.flush()
            finally:
                self._writing.remove(str(path))
                self._writing_done.set()

    @staticmethod
    async def _save_stream(rdr, mw, shorter, ign):
        # helper for .save_stream() to keep the indent levels down

        last_saved = time.monotonic()
        last_saved_count = 0
        TIMEOUT=5
        MAXMSG=100

        while True:
            msg = None
            if last_saved_count:
                with anyio.move_on_after(TIMEOUT):
                    msg = await anext(rdr)
            else:
                msg = await anext(rdr)
            if msg is None or msg is ign:
                pass
            elif isinstance(msg, (list,tuple)):
                path,data,meta = msg
                d,p = shorter.short(path)
                await mw([d,p,data,*meta.dump()])
                last_saved_count += 1
            elif isinstance(msg,CBORTag) and msg.tag == CBOR_TAG_MOAT_FILE_END:
                await mw(msg)
                return
            else:
                await mw(msg)  # XXX
        
            # Ensure that we save the system state often enough.
            t = time.monotonic()
            td = t - last_saved
            if td >= TIMEOUT or last_saved_count >= MAXMSG:
                await mw.flush()
                last_saved = time.monotonic()
                last_saved_count = 0


    async def _flush_deleted(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Background task to remove deleted nodes from the tree
        """
        task_status.started()
        await anyio.sleep(self.cfg.timeout.delete/10)
        t=time.time()

        async def _walk(d) -> bool:
            # return True if we need to keep this

            has_any = False
            await anyio.sleep(0.1)

            # Drop the Meta entry if the deletion was long enough ago
            if d._data is NotGiven and d.meta is not None and t-d.meta.timestamp > self.cfg.timeout.delete:
                d.meta = None
            drop = set()
            for k,v in d.items():
                if await _walk(v):
                    has_any = True
                else:
                    drop.add(k)
            for k in drop:
                del d[k]
            if has_any or d._data is not NotGiven:
                return True
            return d.meta is not None

        while True:
            await _walk(self.data)

            await anyio.sleep(self.cfg.timeout.delete/20)

    async def _save_task(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Background task to periodically restart the saver task
        """
        save = self.cfg.server.save
        dest = anyio.Path(save.dir)
        while True:
            now = datetime.now(UTC)
            fn = dest/now.strftime(save.name)
            await fn.parent.mkdir(exist_ok=True,parents=True)
            await self.run_saver(path=fn)
            if task_status is not None:
                task_status.started()
                task_status = None
            await anyio.sleep(save.interval)

        task_status.started()

    async def run_saver(self, path: anyio.Path = None, save_state: bool=True):
        """
        Start a task that continually saves to disk.

        At most one one saver runs at a time; if a new one is started,
        the old saver is cancelled as soon as the new saver's current state
        is on disk (if told to do so) and it is ready to start writing.

        Args:
          path (str): The file to save to. If ``None``, simply stop any
            already-running log.
          save_state (bool): Flag whether to write the current state.
            If `False` (the default), only write changes.

        """
        res = None
        if path is not None:
            await self._tg.start(
                partial(
                    self.save_stream,
                    path=path,
                    save_state=save_state,
                ),
            )
        else:
            self.write_monitor(self.gen_hdr_stop(reason="log_end"))


    async def _sigterm(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        with anyio.open_signal_receiver(signal.SIGTERM) as r:
            task_status.started()

            async for s in r:
                self._stop_flag.set()
                break

    @property
    async def is_ready(self):
        """Await this to determine if/when the server is operational."""
        await self._ready.wait()

    @property
    async def is_serving(self):
        """Await this to determine if/when the server is serving clients."""
        await self._ready2.wait()

    async def serve(
        self,
        *,
        task_status=anyio.TASK_STATUS_IGNORED,
    ) -> Never:
        """
        The task that opens a backend connection and actually runs the server.
        """
        will_data = attrdict(
            topic=P(":R.run.service.down.main"),
            data=self.name,
            qos=1,
            retain=False,
        )

        # root path
        csr = self.cfg.root
        csr = P(csr) if isinstance(csr, str) else Path.build(csr)
        Root.set(csr)

        self._stop_flag = anyio.Event()
        self._stopped = anyio.Event()

        async with (
            EventSetter(self._stopped),
            Broadcaster(send_last=True) as self.write_monitor,
            get_backend(self.cfg, name="main." + self.name, will=will_data) as self.backend,
            anyio.create_task_group() as _tg,
        ):
            self._tg = _tg

            # Semi-detached taskgroups for clients and listeners

            async def run_tg(task_status):
                async with anyio.create_task_group() as tg:
                    task_status.started(tg)
                    await anyio.sleep_forever()
            client_tg = await _tg.start(run_tg)
            listen_tg = await _tg.start(run_tg)

            # basic infrastructure

            await _tg.start(self._auth_update)
            await _tg.start(self._sigterm)

            # background tasks

            await _tg.start(self._backend_monitor)
            await _tg.start(self._backend_sender)
            await _tg.start(self._read_main)

            # retrieve data

            await _tg.start(self._read_initial)

            # save data

            sd = anyio.Path(self.cfg.server.save.dir)
            if await sd.is_dir():
                await _tg.start(self._save_task)

            # let clients in

            ports = []
            for name, conn in self.cfg.server.ports.items():
                ports.append(await listen_tg.start(self._run_server, client_tg, name, conn))

            if len(ports) == 1:
                link = {"host": ports[0][0], "port": ports[0][1]}
            else:
                link = [{"host": h, "port": p} for h, p in ports]
            self.link_data = link

            # announce us to clients

            ping_ready = anyio.Event()
            await _tg.start(self._pinger, ping_ready)

            if self.cfg.server.standalone:
                await self.set_main_link()
            else:
                await ping_ready.wait()

            # done, ready for service

            task_status.started((self,ports))
            self.logger.debug("STARTUP DONE")

            # maintainance

            await _tg.start(self._flush_deleted)

            # wait for some stop signal

            await self._stop_flag.wait()

            # announce that we're going down

            # TODO listen to this message and possibly take over
            await self.backend.send(topic=P(":R.run.service.down.main"), payload=self.name, retain=False)
            # TODO if we were "it", wait for some other server's announcement

            # stop listeners

            listen_tg.cancel_scope.cancel()

            # stop active clients

            # TODO tell our clients to reconnect to somewhere else
            # TODO wait a few seconds OR until they're all gone
            client_tg.cancel_scope.cancel()

            # stop saving data

            await self._stop_writers()
            # TODO signal our saver to finish
            # TODO wait for our saver to finish

            # Stop the rest
            _tg.cancel_scope.cancel()

    async def _stop_writers(self):
        """Tell our writers to stop"""
        self.write_monitor(self.gen_hdr_stop(reason="Shutdown"))
        while self._writing:
            try:
                with anyio.fail_after(0.5):
                    await self._writing_done.wait()
                    self._writing_done = anyio.Event()
            except TimeoutError:
                for fn in self._writing:
                    self.logger.error("Shutdown: still writing to %r", fn)
                return


    async def stop(self):
        """Tell the server to stop"""
        self._stop_flag.set()
        await self._stopped.wait()

    async def _auth_update(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        # Background task to refresh the auth data
        self.refresh_auth()
        task_status.started()
        while True:
            await anyio.sleep(900)
            self.refresh_auth()

            await anyio.sleep(30)
            self.last_auth = None

    async def _read_main(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Task to read the main service monitoring channel
        """
        async with (
            Broadcaster(send_last=True) as self.service_monitor,
            self.backend.monitor(P(":R.run.service.main")) as mon,
        ):
            task_status.started()
            async for msg in mon:
                self.service_monitor(msg)


    async def _sync_from(self, name: str, data: dict) -> bool:
        """
        Sync from the server indicated by this message.

        Returns True if successful.
        """
        async with BasicLink(self.cfg,name,data) as conn:
            try:
                await self._sync_one(conn)
            except Exception as exc:
                self.logger.warning(
                    "No sync %r: %r",
                    data,
                    exc,
                    exc_info=exc,
                )
                return False
            return True
        return False

    async def _sync_one(self, conn: Conn, prefix:Path=P(":")):
        async with conn.stream_r(P("d.walk"), prefix) as feed:
            pl = PathLongener()
            upd=0
            skp=0
            async for msg in feed:
                d,p,data,*mt = msg
                path = pl.long(d,p)
                meta = MsgMeta.restore(mt)
                meta.source="_Load"
                if self.maybe_update(prefix+path,data,meta):
                    upd += 1
                else:
                    skp += 1
                print(msg)
        self.logger.info("Sync finished. %d new, %d existing", upd,skp)

    async def _read_initial(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Read initial data from either file backup or a remote server.

        Runs in the background if we have initial data.
        """
        ready = anyio.Event()
        main = aiter(self.service_monitor)
        if self.data:
            task_status.started()
            task_status = anyio.TASK_STATUS_IGNORED
            ready.set()

        async with anyio.create_task_group() as tg:
            @tg.start_soon
            async def trigger():
                with anyio.fail_after(self.cfg.server.timeout.startup):
                    await ready.wait()
                task_status.started()
                print(self.name)

            async with anyio.create_task_group() as tgx:
                tgx.start_soon(self._get_remote_data, main, ready)
                tgx.start_soon(self._read_saved_data, ready)

            if not ready.is_set():
                raise RuntimeError("NO DATA")

    async def _read_saved_data(self, ready: anyio.Event):
        save = self.cfg.server.save
        dest = anyio.Path(save.dir)
        if not await dest.is_dir():
            self.logger.info("No saved data in %r",str(dest))
            return

        fs = []
        async for p,d,f in dest.walk():
            print("========", p,d,f)
            for ff in f:
                fs.append(p/ff)
        fs.sort()

        tupd = 0
        while fs:
            fn = fs.pop()
            if str(fn) in self._writing:
                continue
            try:
                async with MsgReader(fn, codec="std-cbor") as rdr:
                    hdr = await anext(rdr)
                    if isinstance(hdr,CBORTag) and hdr.tag == CBOR_TAG_CBOR_FILEHEADER:
                        hdr = hdr.value
                    if not isinstance(hdr,CBORTag) or hdr.tag != CBOR_TAG_MOAT_FILE_ID:
                        raise ValueError(f"First entry is {hdr !r}")

                    pl = PathLongener()
                    upd,skp = 0,0
                    ehdr=None
                    async for msg in rdr:
                        if isinstance(msg, CBORTag):
                            if msg.tag == CBOR_TAG_MOAT_FILE_ID:
                                # concatenated files?
                                if ehdr is None:
                                    raise ValueError("START within file %r",str(fn))
                                # TODO verify that these belong together
                                ehdr = None

                            elif msg.tag == CBOR_TAG_MOAT_FILE_END:
                                if ehdr is not None:
                                    raise ValueError("Duplicate END in %r",str(fn))
                                ehdr=msg
                                break
                            continue
                        d,p,data,*mt = msg
                        path = pl.long(d,p)
                        meta = MsgMeta.restore(mt)
                        meta.source="_file"
                        if self.maybe_update(path,data,meta):
                            # Entries that have been deleted don't count as updates
                            if data is not NotGiven:
                                upd += 1
                        else:
                            skp += 1

                    self.logger.info("Restore %r: %d/%d", str(fn),upd,skp)
                    tupd += upd
                    if not upd and ehdr is not None and "error" not in ehdr.data:
                        break
            except Exception:
                raise

        if tupd:
            ready.set()

    async def _get_remote_data(self, main: BroadcastReader, ready: anyio.Event):
        seen = defaultdict(lambda: 0)
        async for msg in main:
            if msg.meta.origin == self.name:
                continue  # XXX stale
            if await self._sync_from(msg.meta.origin, msg.data):
                ready.set()
                return
            sn = seen[msg.meta.origin]
            if sn > 2:
                return
            seen[msg.meta.origin] = sn+1

        pass


    async def _run_server(self, tg, name, cfg, *, task_status=anyio.TASK_STATUS_IGNORED):
        """runs a listener on a single port"""
        lcfg = attrdict()
        if "host" in cfg:
            lcfg.local_host = cfg.host
        if "port" in cfg:
            lcfg.local_port = cfg.port
        # TODO SSL and/or whatnot
        async with await anyio.create_tcp_listener(**lcfg) as listener:
            task_status.started(listener.extra(SocketAttribute.local_address))
            await listener.serve(partial(self._client_task, name), task_group=tg)

    async def _client_task(self, name, stream):
        """
        Manager for a single client connection.

        The acctual work happens in `ServerClient.run`. This wrapper
        mainly tries to send a message to the client that states what went
        wrong on the server.
        """
        c = None
        try:
            c = ServerClient(server=self, name=name, stream=stream)
            try:
                self._clients.add(c)
                await c.run()
            finally:
                self._clients.remove(c)
        except (ClosedResourceError, anyio.EndOfStream):
            self.logger.debug("XX %d closed", c.client_nr)
        except BaseException as exc:
            CancelExc = anyio.get_cancelled_exc_class()
            if hasattr(exc, "split"):
                exc = exc.split(CancelExc)[1]
            elif hasattr(exc, "filter"):
                # pylint: disable=no-member
                exc = exc.filter(lambda e: None if isinstance(e, CancelExc) else e, exc)

            if exc is not None and not isinstance(exc, CancelExc):
                if isinstance(exc, (ClosedResourceError, anyio.EndOfStream)):
                    self.logger.debug("XX %d closed", c.client_nr)
                else:
                    self.logger.exception("Client connection killed", exc_info=exc)
            if exc is None:
                exc = "Cancelled"
            try:
                with anyio.move_on_after(0.02, shield=True):
                    if c is not None:
                        await c.cmd(P("i.error"), str(exc))
            except (anyio.BrokenResourceError, anyio.ClosedResourceError):
                pass

        finally:
            with anyio.move_on_after(2, shield=True):
                await stream.aclose()
