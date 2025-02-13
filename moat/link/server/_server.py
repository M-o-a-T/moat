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

from moat.lib.cmd import CmdHandler
from moat.lib.cmd.anyio import run as run_cmd_anyio
from moat.link.auth import AnonAuth, TokenAuth
from moat.link.conn import SubConn, CmdCommon
from moat.link.backend import get_backend
from moat.link.exceptions import ClientError
from moat.link.meta import MsgMeta
from moat.util.cbor import StdCBOR
from moat.lib.codec.cbor import Tag as CBORTag, CBOR_TAG_CBOR_FILEHEADER

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


@define
class SaveWriter(CtxObj):
    """
    This class writes a MoaT savefile.

    Usage::

        async with SaveWriter("Started yesterday",
                              type="main", time=time()) as sw:
            for x in data:
                sw.write(x.path,x.data,x.meta)
            sw["time"] = time()
        pass # here the file is closed and properly terminated
    """

    _fn: anyio.Path
    _txt: str
    _kw: dict[str, Any]
    _kw2: dict[str, Any]
    _fd: anyio.File = field(init=False)
    _pl: PathShortener = field(init=False)
    _codec: StdCBOR = field(init=False)

    def __init__(self, fn: anyio.Path, text: str, **kw):
        self._fn = fn
        self._txt = txt
        self._kw = kw
        self._kw2 = {}

    def __setattr__(self, k, v):
        self._kw2[k] = v

    async def _ctx(self):
        self._pl = PathShortener()
        self._codec = StdCBOR()
        async with await self._fn.open("wb") as self._fd:
            await self._fd.write(self._codec.encode(gen_start(self._txt, self._kw)))
            await self._fd.flush()
            yield self
            await self._fd.write(self._codec.encode(gen_stop(self._kw2)))
            await self._fd.flush()

    async def write(self, path, data, meta):
        d, p = self._pl(path)
        await self._fd.write(self._codec.encode((d, p, data, meta)))

    async def flush(self):
        await self._fd.flush()


class MonitorWriter(CtxObj):
    """
    This class monitors the MoaT change stream and writes it to a file.

    Usage:

        async with MonitorWriter(server.write_monitor,
                                 "see SaveWriter args",
                                 prev=prev_save_filename) as mw:
            pass # savefile is opened and hooked up
            await switch_save_stream.wait()
            mw["time"] = time()
            mw["next"] = next_save_name()
        pass # monitor and file are closed here
    """

    _sc: anyio.CancelScope
    _mon: Broadcaster
    _a: list
    _kw: dict
    _wr: SaveWriter | None = None

    def __init__(self, mon: Broadcaster, *a, **kw):
        self._a = a
        self._kw = kw
        self._mon = mon

    def __setattr__(self, k, v):
        self._wr[k] = v

    async def _ctx(self):
        async def _write(it, wr, evt, *, task_status: anyio.TaskStatus):
            with anyio.CancelScope() as sc:
                task_status.started(sc)
                try:
                    async for p, d, m in it:
                        await wr.write(p, d, m)
                finally:
                    evt.set()

        async with (
            _mon.reader(99999) as it,
            SaveWriter(*self._a, **self._kw) as self._wr,
            anyio.create_task_group() as tg,
        ):
            cs = await tg.start(_write, it, wr)
            yield self
            cs.cancel()

            await anyio.sleep(0.01)
            # bail out if we've been cancelled


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
        await self.server.run_saver(path=msg.path, save_state=msg.get("fetch", False))
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
    cur_auth: str

    _saver: SaveWriter | None = None

    def __init__(self, cfg: dict, name: str, init: Any = NotGiven):
        self.data = Node()
        self.name = name
        self.cfg = cfg

        if init is not NotGiven:
            self.data.set(Path(), init, MsgMeta(origin="INIT"))

        self.logger = logging.getLogger("moat.link.server." + name)

        # connected clients
        self._clients: set[ServerClient] = set()

        self.cur_auth = gen_ident(20)

    async def _run_save(self, fn: anyio.Path):
        with anyio.CancelScope() as sc:
            async with SaveWriter():
                pass

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
        self.logger.info("********* Mon start")
        chop = len(self.cfg.root)
        async with self.backend.monitor(P(":R.#"), raw=False) as stream:
            self.logger.info("********* Mon started")
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
        async for p,d,m in rdr:
            if m.source == "Mon":
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

                if authoritative:
                    # … or not.
                    self._discard_all_missing()
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

        async with MsgReader(path=path, stream=stream, codec="moat.util.cbor") as rdr:
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

    def _discard_all_missing(self):
        for n in self._nodes.values():
            if not n.tick:
                continue
            lk = n.local_missing

            if len(lk):
                n.report_superseded(lk, local=True)

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

        return gen_change(TAG_Mchg, kw)
    

    def get_state(self):
        return dict("")

    async def save(self, path: str = None, stream=None, **kw):
        """Save the current state to ``path`` or ``stream``."""
        shorter = PathShortener([])
        async with MsgWriter(path=path, stream=stream, codec="moat.util.cbor") as mw:
            await self._save(mw, shorter, name=path, **kw)

    async def save_stream(
        self,
        path: str = None,
        stream: anyio.abc.Stream = None,
        save_state: bool = False,
        done: ValueEvent = None,
        done_val=None,
    ):
        """Save the current state to ``path`` or ``stream``.
        Continue writing updates until cancelled.

        Args:
          path: The file to save to.
          stream: the stream to save to.
          save_state: Flag whether to write the current state.
            If ``False`` (the default), only write changes.
          done: set when writing changes commences, signalling
            that the old save file (if any) may safely be closed.

        Exactly one of ``stream`` or ``path`` must be set.

        This task flushes the current buffer to disk when one second
        passes without updates, or every 100 messages.
        """
        shorter = PathShortener([])

        async with MsgWriter(path=path, stream=stream) as mw:
            msg = await self.get_state(nodes=True, known=True, deleted=True)
            # await mw({"info": msg})
            await mw(msg)  # XXX legacy
            last_saved = time.monotonic()
            last_saved_count = 0

            async with Watcher(self.root, full=True) as updates:
                await self._ready.wait()

                if save_state:
                    await self._save(mw, shorter, full=True)

                await mw.flush()
                if done is not None:
                    s = done.set(done_val)
                    if s is not None:
                        await s

                cnt = 0
                while True:
                    # This dance ensures that we save the system state often enough.
                    t = time.monotonic()
                    td = t - last_saved
                    if td >= 60 or last_saved_count > 1000:
                        msg = await self.get_state(nodes=True, known=True, deleted=True)
                        # await mw({"info": msg})
                        await mw(msg)  # XXX legacy
                        await mw.flush()
                        last_saved = time.monotonic()
                        last_saved_count = 0
                        td = -99999  # translates to something large, below
                        cnt = 0

                    try:
                        with anyio.fail_after(1 if cnt else 60 - td):
                            msg = await updates.__anext__()
                    except TimeoutError:
                        await mw.flush()
                        cnt = 0
                    else:
                        msg = msg.serialize()
                        shorter(msg)
                        last_saved_count += 1
                        await mw(msg)
                        if cnt >= 100:
                            await mw.flush()
                            cnt = 0
                        else:
                            cnt += 1

    async def _saver(
        self,
        path: str = None,
        stream=None,
        done: ValueEvent = None,
        save_state=False,
    ):
        with anyio.CancelScope() as s:
            sd = anyio.Event()
            state = (s, sd)
            self._savers.append(state)
            try:
                await self.save_stream(
                    path=path,
                    stream=stream,
                    done=done,
                    done_val=s,
                    save_state=save_state,
                )
            except OSError as err:
                if done is None:
                    raise
                done.set_error(err)
            finally:
                sd.set()

    async def _flush_deleted(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        task_status.started()
        await anyio.sleep(100)

        async def _walk(d) -> bool:
            # return True if we need to keep this
            has_any = False
            await anyio.sleep(0.1)
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
            return d.meta is None or d.meta.timestamp < self.cfg.timeout.delete

        while True:
            await _walk(self.data)

            await anyio.sleep(self.cfg.timeout.delete/20)

    async def run_saver(self, path: anyio.Path = None, wait:bool=True):
        """
        Start a task that continually saves to disk.

        At most one one saver runs at a time; if a new one is started,
        the old saver is cancelled as soon as the new saver's current state
        is on disk (if told to do so) and it is ready to start writing.

        Args:
          path (str): The file to save to. If ``None``, simply stop any
            already-running log.
          stream (anyio.abc.Stream): the stream to save to.
          save_state (bool): Flag whether to write the current state.
            If ``False`` (the default), only write changes.
          wait: wait for the save to really start.

        """
        done = ValueEvent() if wait else None
        res = None
        if path is not None:
            await self.spawn(
                partial(
                    self._saver,
                    path=path,
                    stream=stream,
                    save_state=save_state,
                    done=done,
                ),
            )
            if wait:
                res = await done.get()

        # At this point the new saver is operational, so we cancel the old one(s).
        while self._savers is not None and self._savers[0][0] is not res:
            s, sd = self._savers.pop(0)
            s.cancel()
            await sd.wait()

    async def _sigterm(self):
        with anyio.open_signal_receiver(signal.SIGTERM) as r:
            async for s in r:
                for s, sd in self._savers:
                    s.cancel()
                    await sd.wait()
                break
        os.kill(os.getpid(), signal.SIGTERM)

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
        tg: anyio.abc.TaskGroup = None,
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

        async with (
            anyio.create_task_group() as _tg,
            Broadcaster(send_last=True) as self.write_monitor,
            get_backend(self.cfg, name="main." + self.name, will=will_data) as self.backend,
        ):
            if tg is None:
                tg = _tg

            ports = []

            h1 = None
            for name, conn in self.cfg.server.ports.items():
                if h1 is None:
                    h1 = conn["host"]
                ports.append(await _tg.start(self._run_server, name, conn))

            if len(ports) == 1:
                link = {"host": ports[0][0], "port": ports[0][1]}
            else:
                link = [{"host": h, "port": p} for h, p in ports]
            self.link_data = link

            await tg.start(self._backend_monitor)
            await tg.start(self._backend_sender)
            await tg.start(self._read_main)
            await tg.start(self._read_initial)

            ping_ready = anyio.Event()
            _tg.start_soon(self._pinger, ping_ready)
            if not self.cfg.server.standalone:
                await ping_ready.wait()

            if self.cfg.server.standalone:
                await self.set_main_link()

            task_status.started(ports)
            self.logger.debug("STARTUP DONE")

            await tg.start(self._flush_deleted)

            # Auth updating
            while True:
                await anyio.sleep(900)
                self.refresh_auth()

                await anyio.sleep(300)
                self.last_auth = None

    async def _read_main(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Task to read the main channel
        """
        async with (
            Broadcaster(send_last=True) as self.service_monitor,
            self.backend.monitor(P(":R.run.service.main")) as mon,
        ):
            task_status.started()
            async for msg in mon:
                self.service_monitor(msg)

    async def _get_remote_data(self, main: BroadcastReader, ready: anyio.Event):
        try:
            with anyio.fail_after(self.cfg.server.timeout.monitor):
                msg = await anext(main)
        except TimeoutError:
            return  # no entry yet

        if msg.meta.origin == self.name:
            self.logger.notice("no remote sync: from myself")
            return
        if msg.meta.timestamp < 1.5 * self.cfg.server.timeout.refresh:
            self.logger.notice("no remote sync: too old")
            return
        if await self._sync_from(msg.meta.origin, msg.data):
            ready.set()

    async def _sync_from(self, name: str, data: dict) -> bool:
        """
        Sync from the server indicated by this message.

        Returns True if successful.
        """
        links = msg.data.link
        if isinstance(links, dict):
            links = (links,)
        for link in links:
            try:
                async with Conn(
                    me=self.name,
                    them=msg.meta.origin,
                    host=link["host"],
                    port=link["port"],
                    token=data.get("token"),
                ) as conn:
                    if conn.auth is not True:
                        self.logger.warning("No auth: sync from %s %s", msg.meta.origin, link)
                        continue
                    try:
                        await self._sync_one(conn)
                    except Exception as exc:
                        self.logger.warning(
                            "No sync from %s %s: %r",
                            msg.meta.origin,
                            msg.data,
                            exc,
                            exc_info=exc,
                        )
                        return False
                    return True

            except Exception as exc:
                self.logger.warning(
                    "No connection to %s %s: %r",
                    msg.meta.origin,
                    link,
                    exc,
                    exc_info=exc,
                )
        return False

    async def _sync_from(self, conn: Conn):
        async with conn.stream_r(P("s.full"), root=P(":")) as feed:
            pl = PathLongener()
            async for msg in feed:
                print(msg)
        raise RuntimeError("TODO")

    async def _read_saved_data(self, ready: anyio.Event):
        """
        Scan our save directory. Read all entries in reverse order
        and stop when we got them all.
        """

        incomplete: bool = False
        expected: str | None = None

        @define
        class Reader(CtxObj):
            """
            Read a file, returning decoded chunks.
            """

            fn: anyio.Path

            async def _ctx(self):
                async with await fn.open("rb") as self._f:
                    yield self

            def __aiter__(self):
                return self._iter()

            async def _iter(self):
                codec = StdCBOR()
                while True:
                    for data in codec.feed(await self._f.read(4096)):
                        yield data

        async def _read_data(fn):
            try:
                async with await Reader(fn) as rdr:
                    it = aiter(rdr)
                    pl = PathLongener()

                    head = await anext(it)
                    if head.tag == CBOR_TAG_CBOR_FILEHEADER:
                        head = head.value
                    if head.tag != CBOR_TAG_MOAT_FILE_ID:
                        raise ValueError("missing start tag")
                    dh = to_attrdict(head.value)
                    if dh.source != "main":
                        raise ValueError("not from main")

                    async for d in it:
                        if isinstance(d, CBORTag) and d.tag == CBOR_TAG_MOAT_FILE_END:
                            return dh, d.value
                        depth, path, data, meta = d
                        path = pl.long(depth, path)
                        self.maybe_update(path, data, meta)

                raise ValueError("no end tag")

            except Exception as exc:
                raise BadFile(fn, repr(exc)) from exc

        async def _read_subdirs(d):
            names = []
            async for fn in await d.iterdir():
                if fn.startswith("."):
                    continue
                names.append(fn)
            names.sort()

            while names:
                fn = names.pop()
                dd = d / fn
                if fn.suffix == ".mld":
                    if await _read_data(dd):
                        return True
                elif await fn.is_dir():
                    if await _read_subdirs(dd):
                        return True

        d = anyio.Path(self.cfg.server.save.dir)
        if await self._read_subdirs(d):
            ready.set()

    async def _read_initial(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Read initial data from either file backup or a remote server.
        """
        ready = anyio.Event()
        main = aiter(self.service_monitor)
        if self.data:
            task_status.started()
            task_status = anyio.TASK_STATUS_IGNORED
            ready.set()
        async with anyio.create_task_group() as tg:
            async with anyio.create_task_group() as tgx:
                tg.start_soon(self._get_remote_data, main, ready)
                tg.start_soon(self._read_saved_data, ready)
            if not ready.is_set():
                self.logger.warning("No data. Waiting for supplier.")
                for msg in main:
                    try:
                        await self._sync_from(msg.meta.origin, msg.data)
                    finally:
                        pass  # XXX

    async def _read_saved_data(self, ready: anyio.Event):
        pass

    async def _get_remote_data(self, main: BroadcastReader, ready: anyio.Event):
        pass

    async def _run_server(self, name, cfg, *, task_status=anyio.TASK_STATUS_IGNORED):
        lcfg = attrdict()
        if "host" in cfg:
            lcfg.local_host = cfg.host
        if "port" in cfg:
            lcfg.local_port = cfg.port
        # TODO SSL and/or whatnot
        async with await anyio.create_tcp_listener(**lcfg) as listener:
            task_status.started(listener.extra(SocketAttribute.local_address))
            await listener.serve(partial(self._client_task, name))

    async def _client_task(self, name, stream):
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


class old_stuff:
    async def serve_old(self, log_path=None, log_inc=False, force=False, ready_evt=None):
        """Task that opens a backend connection and actually runs the server.

        Args:
          ``setup_done``: optional event that's set when the server is initially set up.
          ``log_path``: path to a binary file to write changes and initial state to.
          ``log_inc``: if saving, write changes, not the whole state.
          ``force``: start up even if entries are missing
        """
        # async with ()
        self.force_startup = force
        back = get_backend(self.cfg.server.backend)
        try:
            conn = self.cfg.server[self.cfg.server.backend]
        except KeyError:
            conn = self.cfg.server.connect
        async with back(**conn) as backend:
            # pylint: disable=attribute-defined-outside-init

            # Collect all "info/missing" messages seen since the last
            # healed network split so that they're only sent once.
            self.seen_missing = {}

            # Is the missing-items-sender running?
            # None=no, otherwise flag whether it should run another round
            self.sending_missing = None

            # Nodes which list missing events
            self.fetch_missing = set()

            # Flag whether do_fetch_missing is running (True)
            # or do_send_missing is running (False)
            # or neither (None)
            self.fetch_running = None

            # Set when self.node.tick is no longer None, i.e. we have some
            # reasonable state
            self._ready = anyio.Event()

            # set when we're ready to accept client connections
            self._ready2 = anyio.Event()

            self.backend = backend

            # Sync recovery steps so that only one node per branch answers
            self._recover_event1 = None
            self._recover_event2 = None

            # local and remote node lists
            self._recover_sources = None

            # Cancel scope; if :meth:`recover_split` is running, use that
            # to cancel
            self._recover_tasks = {}

            # used to sync starting up everything so no messages get either
            # lost, or processed prematurely
            delay = anyio.Event()
            delay2 = anyio.Event()
            delay3 = anyio.Event()

            if log_path is not None:
                await self.run_saver(path=log_path, save_state=not log_inc, wait=False)

            # Link up our "user_*" code
            for d in dir(self):
                if d.startswith("user_"):
                    await self.spawn(self.monitor, d[5:], delay)

            await delay3.wait()

            if self._init is not NotGiven:
                assert self.node.tick is None
                self.node.tick = 0
                async with self.next_event() as event:
                    await self.root.set_data(event, self._init, tock=self.tock, server=self)

            await self.spawn(self._sigterm)

            # send initial ping
            await self.spawn(self._pinger, delay2)

            await anyio.sleep(0.1)
            delay.set()
            await self._check_ticked()  # when _init is set
            await delay2.wait()
            await self._ready.wait()

            cfgs = self.cfg.server.bind
            cfg_b = self.cfg.server.bind_default
            evts = []
            async with anyio.create_task_group() as tg:
                for n, cfg in enumerate(cfgs):
                    cfg = combine_dict(cfg, cfg_b, cls=attrdict)
                    evt = anyio.Event()
                    evts.append(evt)
                    tg.start_soon(self._accept_clients, tg, cfg, n, evt)
                for evt in evts:
                    await evt.wait()

                self._ready2.set()
                if ready_evt is not None:
                    ready_evt.set()
                # end of server taskgroup
            # end of server
        # end of backend client

    async def _accept_clients(self, tg, cfg, n, evt):
        ssl_ctx = gen_ssl(cfg["ssl"], server=True)
        cfg = combine_dict({"ssl": ssl_ctx}, cfg, cls=attrdict)

        def rdy(n, server):
            if n == 0:
                port = server.extra(SocketAttribute.local_address)
            self.ports = [port]
            evt.set()

        await run_tcp_server(self._connect, tg=tg, _rdy=partial(rdy, n), **cfg)
