"""
The main MoaT-Link Server
"""

from __future__ import annotations

import anyio
import logging
import signal
import time
import anyio.abc
import random
import os
from platform import uname
from anyio.abc import SocketAttribute
from contextlib import asynccontextmanager, nullcontext
from datetime import UTC, datetime
from functools import partial
from attrs import define,field
from collections.abc import Sequence
from asyncactor import (
    Actor,
    GoodNodeEvent,
    RecoverEvent,
    TagEvent,
    PingEvent,
)
from asyncactor.backend import get_transport
from mqttproto import QoS

from moat.util import (
    MsgReader,
    MsgWriter,
    NotGiven,
    P,
    Path,
    PathLongener,
    PathShortener,
    Root,
    attrdict,
    gen_ident,
    to_attrdict,
    id2str,
)
from moat.lib.cmd.base import MsgSender, MsgHandler
from moat.lib.cmd.anyio import run as run_cmd_anyio
from moat.lib.codec.cbor import CBOR_TAG_CBOR_LEADER, Tag
from moat.link.auth import AnonAuth
from moat.link.backend import get_backend, Backend
from moat.link.client import BasicLink, LinkCommon
from moat.link.exceptions import ClientError
from moat.link.hello import Hello
from moat.link.meta import MsgMeta
from moat.link.node import Node
from moat.util.broadcast import Broadcaster, BroadcastReader
from moat.util.cbor import (
    CBOR_TAG_MOAT_CHANGE,
    CBOR_TAG_MOAT_FILE_END,
    CBOR_TAG_MOAT_FILE_ID,
)
from moat.util.exc import exc_iter

from collections import defaultdict
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from pathlib import Path as FSPath
    from moat.lib.cmd.msg import Msg
    from moat.link.backend import Message

    PathType = anyio.Path|FSPath|str


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

def tag_check(tags:Sequence[Tag]) -> bool:
    """
    Check that these tags describe a complete dump
    """
    if len(tags) < 2:
        return False
    t=tags[0]
    if t.tag != CBOR_TAG_MOAT_FILE_ID:
        return False
    t=t.value[1]
    if t.get("mode","") not in {"full","init"}:
        return False

    t = tags[-1]
    if t.tag != CBOR_TAG_MOAT_FILE_END:
        return False

    return True


def _get_my_ip(ip6:bool=False):
    """
    Find my IP address
    :return:
    """
    import socket
    s = socket.socket(socket.AF_INET6 if ip6 else socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("2606:4700:4700::1111" if ip6 else "1.1.1.1", 53))
    ip = s.getsockname()[0]
    s.close()
    return ip


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


class ServerClient(LinkCommon):
    """Represent one (non-server) client."""

    _hello: Hello | None = None
    _auth_data: Any = None
    is_server:bool = False
    protocol_version: int = -1
    prefix: str
    name: str

    def __init__(self, server: Server, prefix: str, stream: Stream):
        self.server = server
        self.prefix = prefix
        self.stream = stream

        # there sustained rate might be > 10 connections per second.
        # >100 requires rate limiting.
        global _client_nr
        t = int(time.time()*100-175000000000)
        if t < 0:  # testing. Revert.
            t += 175000000000
        if _client_nr == 0 or _client_nr < t:
            _client_nr = t
        else:
            _client_nr += 1
            if _client_nr > t+1000:
                raise RuntimeError("The connection rate is too high!")
        self.client_nr = id2str(_client_nr)
        self.name=f"{self.prefix}.C{self.client_nr}"

        self.logger = logging.getLogger(f"moat.link.server.{prefix}.{self.client_nr}")

    @property
    def sender(self) -> MsgSender:
        return self._sender

    async def aclose(self):
        """
        Shut this client down
        """
        self.tg.cancel_scope.cancel()

    async def run(self):
        """Main loop for this client connection."""

        self.logger.debug("START %s C_%s", self.name, self.client_nr)
        self._hello = Hello(
            them=self.name,
            me=self.server.name,
            me_server=True,
            auth_in=[AnonAuth()],
        )
        async with (
            anyio.create_task_group() as self.tg,
            run_cmd_anyio(self, self.stream) as cmd,
        ):
            self._sender = MsgSender(cmd)

            # basic setup
            them = None
            try:
                if await self._hello.run(MsgSender(cmd)) is False or not (
                    auth := self._hello.auth_data
                ):
                    self.logger.debug("NO %s", self.client_nr)
                    return
                them = self._hello.them
                self.is_server = self._hello.they_server
                try:
                    self.server.rename_client(self,them)
                except ValueError:
                    self.logger.warning("Rename to %s failed", them)

                if not self.is_server and "." not in them:
                    # announce fixed-name client
                    # The condition *must* match the 'vanish' message
                    await self.server.backend.send(P(":R.run.service.main.client")/them,self.server.name, retain=True)
                self.protocol_version = self._hello.protocol_version
            finally:
                del self._hello

            self._auth_data = auth

            # periodic ping
            while True:
                # XXX only when otherwise idle
                await anyio.sleep(self.server.cfg.server.probe.repeat)
                with anyio.fail_after(self.server.cfg.server.probe.timeout):
                    await self._sender.cmd(P("i.乒"))

    @property
    def auth_data(self):
        """
        Retrieve auth data.

        These might be stored in the Hello processor while startup is incomplete.
        """
        if self._hello is not None:
            return self._hello.auth_data
        return self._auth_data

    def handle(self, msg, rpath, *sub) -> Awaitable[Any]:
        """
        Message handlers that intercepts commands, as long as no
        authorization has taken place
        """
        if self._hello is not None and self._hello.auth_data is None:
            return self._hello.handle(msg, rpath, *sub)

        return super().handle(msg, rpath, *sub)

    doc_d_get = dict(_d="get subnode data", _r=["Any:Data", "MsgMeta"], _0="Path")

    async def stream_d_get(self, msg):
        """Get the data of a sub-node.

        Arguments:
        * path

        Result:
        * data
        * metadata
        """
        d = self.server.data[msg[0]]
        await msg.result(d.data, *d.meta.dump())

    doc_d = dict(_d="Data access commands")

    def sub_d(self, msg: Msg, rcmd: list) -> Awaitable:
        "Local subcommand redirect for 'd'"
        return self.handle(msg, rcmd, "d")

    doc_e = dict(_d="Error handling commands")

    def sub_e(self, msg: Msg, rcmd: list) -> Awaitable:
        "Local subcommand redirect for 'e'"
        return self.handle(msg, rcmd, "e")

    doc_i = dict(_d="Informational commands")

    def sub_i(self, msg: Msg, rcmd: list) -> Awaitable:
        "Local subcommand redirect for 'i'"
        return self.handle(msg, rcmd, "i")

    doc_s = dict(_d="Data load/save commands")

    def sub_s(self, msg: Msg, rcmd: list) -> Awaitable:
        "Local subcommand redirect for 's'"
        return self.handle(msg, rcmd, "s")


    doc_cl = dict(_d="Access to named clients")

    def sub_cl(self, msg: Msg, rcmd: list) -> Awaitable:
        "Local subcommand redirect for 'cl'"
        return self.server.sub_cl(msg,rcmd)

    def stream_cl(self, msg:Msg) -> Awaitable:
        "Send the list of currently-known clients"
        return self.server.stream_cl(msg)


    doc_d_list = dict(_d="get subnode child names", _r=["Any:Data", "MsgMeta"], _o="str")

    async def stream_d_list(self, msg):
        """Get the child names of a sub-node.
        Arguments:
        * path

        Stream:
        * strings
        """

        async with msg.stream_out():
            for k in list(self.server.data[msg[0]].keys()):
                await msg.send(k)

    doc_d_walk = dict(
        _d="get subtree",
        _0="Path",
        _1="float:mintime",
        _2="int:mindepth",
        _3="int:maxdepth",
        _r=dict(_0="int:depth", _1="Path:sub", _2="Any:data", _99="MsgMeta"),
        _o="str",
    )

    async def stream_d_walk(self, msg):
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
            try:
                nd = n.data
            except ValueError:
                return
            d, sp = ps.short(p)
            await msg.send(d, sp, nd, *n.meta.dump())

        try:
            d = self.server.data.get(msg[0], create=False)
        except KeyError:
            async with msg.stream_out():
                return

        ts = msg.get(1, 0)
        xmin = msg.get(2, 0)
        xmax = msg.get(3, 9999999)
        async with msg.stream_out():
            await d.walk(_writer, timestamp=ts, min_depth=xmin, max_depth=xmax)

    doc_d_set = dict(_d="set value", _0="Path", _1="Any", _99="MsgMeta:optional", t="Time of last change")

    async def cmd_d_set(self, path, value, meta: MsgMeta | None = None, t:float|None=None):
        """Set a node's value.

        Arguments:
        * pathname
        * value
        * optional: new metadata
        * optional: t: timestamp of last change

        You should not call this. Send to the MQTT topic directly.
        """
        if meta is None:
            meta = MsgMeta(origin=self.name)
        meta.source = "Client"

        try:
            node = self.server.data.get(path)
        except ValueError:
            res = None
        else:
            if t is not None and (node.meta is None or abs(node.meta.timestamp-t) > .001):
                raise OutOfDateError(node.meta)
            try:
                res = node.data,*(node.meta.dump() if node.meta is not None
                                  else ())
            except ValueError:
                res = NotGiven,*(node.meta.dump() if node.meta is not None else ())
        self.server.maybe_update(path, value, meta)
        return res

    doc_d_delete = dict(_d="delete value", _0="Path", _99="MsgMeta:optional", t="Time of+ last change")

    async def cmd_d_delete(self, path, meta=None, t:float|None=None):
        """Delete a node's value.

        Arguments:
        * pathname
        * optional: new metadata
        * optional: t: timestamp of last change

        You should only call this if you don't know whether the data exists.
        If you do, send an empty value to the MQTT topic directly.
        """
        if meta is None:
            meta = MsgMeta(origin=self.name)
        meta.source = "Client"

        try:
            node = self.server.data[path]
            dv = node.data
            dm = node.meta
        except (KeyError,ValueError):
            node = None
        else:
            if t is not None and abs(node.meta.timestamp-t) > .001:
                raise OutOfDateError(node.meta)
            self.server.maybe_update(path, NotGiven, meta)

        if node is None:
            return None
        else:
            return dv, *dm.dump()

    doc_e_exc = dict(_d="Report an exception",_0="path:Path", _1="exc:Error", _k="any")

    def stream_e_exc(self, msg:Msg) -> Awaitable:
        """Report not-an-error"""
        if len(msg.args) > 2:
            msg.kw['_args'] = msg.args[2:]
        return self.server.set_error(msg[0], msg[1], msg.kw, MsgMeta(origin=self.name))

    doc_e_info = dict(_d="Report a non-exceptional anomaly",_0="path:Path", _k="any")

    def stream_e_info(self, msg:Msg) -> Awaitable:
        """Report not-an-error"""
        if len(msg.args) > 2:
            msg.kw['_args'] = msg.args[2:]
        return self.server.set_error(msg[0], msg[1], msg.kw, MsgMeta(origin=self.name))

    doc_e_ack = dict(_d="Acknowledge an error",_0="path:Path", _k="any",
                     ack="None|bool|float:")

    def stream_e_ack(self, msg:Msg) -> Awaitable:
        """Acknowledge an error"""
        if len(msg.args) > 2:
            msg.kw['_args'] = msg.args[2:]
        msg.kw["_ack"]=True
        return self.server.set_error(msg[0], NotGiven, msg.kw, MsgMeta(origin=self.name))

    doc_e_ok = dict(_d="State is OK", _0="path:Path", _k="any")

    def stream_e_ok(self, msg:Msg) -> Awaitable:
        """Report not-an-error"""
        if len(msg.args) > 1:
            msg.kw['_args'] = msg.args[1:]
        return self.server.set_error(msg[0], None, msg.kw, MsgMeta(origin=self.name))

    doc_e_mon = dict(_d="Wrapper", _0="path:Path", _i="logging data", _k="any")
    async def stream_e_mon(self, msg:Msg):
        path = msg[0]
        kw = msg.kw
        meta = MsgMeta(origin=self.name)
        kw["_start"]=time.time()
        kw["_log"] = log = []
        try:
            async with msg.stream_in() as mon:
                async for msg in mon:
                    if (a := msg.args):
                        if msg.kw:
                            a.append(msg.kw)
                        elif isinstance(a[-1],dict):
                            a.append({})
                        log.append(a)
                    elif msg.kw:
                        log.append(msg.kw)
        except Exception as exc:
            err = exc
        except BaseException:
            err = "BaseExc"
            raise
        else:
            err = None
        finally:
            kw["_stop"]=time.time()
            if err is not None:
                kw["_exc"] = err
            with anyio.move_on_after(2,shield=True):
                await self.server.set_error(path,err,kw,MsgMeta(origin=self.name))


    doc_i_state = dict(_d="state", _r="MsgMeta:optional")

    async def cmd_i_state(self):
        """Return some info about this node's internal state"""
        return self.server.get_state()

    doc_i_error = dict(_d="last disconnect error", _r="Any:error")

    def cmd_i_error(self, last_name: str|None = None) -> Any:
        """Return some info about the reason my link got disconnected"""
        return self.server.get_cached_error(last_name or self.name)

    doc_i_stamp = dict(_d="stamp", _r="int:timestamp sequence#")

    def cmd_i_stamp(self) -> int:
        """Return a new timestamp value"""
        return self.server.new_stamp()

    doc_i_sync = dict(_d="sync", _0="int:timestamp sequence#")

    def cmd_i_sync(self, stamp) -> Awaitable[None]:
        """wait until the server received this stamp#"""
        return self.server.wait_stamp(stamp)

    doc_d_deltree = dict(_d="drop a subtree", _0="Path", _r="int:#nodes", _o="node data")

    async def stream_d_deltree(self, msg):
        """Delete a node's value.
        Sub-nodes are cleared (after their parent).
        """
        root = msg[0]
        if not root:
            raise ClientError("You can't delete the root node")
        ps = PathShortener(root)
        data = self.server.data[root]
        res = 0

        async with msg.stream_w() if msg.can_stream else nullcontext() as ws:

            async def _del(path:Path, entry:Node):
                if entry.data is NotGiven:
                    return

                meta = MsgMeta(origin=self.name)
                meta.source = "Client"

                data = entry.data
                if self.server.maybe_update(path, NotGiven, meta) and ws is not None:
                    await ws.send(*ps.short(path), data, *meta.dump())

                nonlocal res
                res += 1

            await data.walk(_del)
            await msg.result(res)


    doc_s_error = dict(_d="save error log", _0="str:filename", state="bool:include current state")

    async def cmd_s_error(self, path: str, *, state: bool = False):
        await self.server.run_errsaver(path, save_state=state)
        return True

    doc_s_log = dict(_d="save updates", _0="str:filename", state="bool:include current state")

    async def cmd_s_log(self, path: str, *, state: bool = False):
        await self.server.run_saver(path, save_state=state)
        return True


    doc_s_save = dict(_d="save current state", _0="str:filename", prefix="path:subtree")

    async def cmd_s_save(self, path: str, prefix=Path()):
        await self.server.save(path, prefix=prefix)

        return True

    doc_s_load = dict(_d="load state", _0="str:filename", prefix="path:subtree")

    async def cmd_s_load(self, path, *, prefix=Path()):
        return await self.server.load_file(fn=path, prefix=prefix)


@define
class ClientStub:
    """
    This is an entry in the client list that redirects to the server
    which this client is connected to.
    """
    server:Server = field()
    name:str = field()
    client:str = field()

    @property
    def sender(self):
        "Stub, returns self"
        return self

    async def handle(self, msg: Msg, rcmd: list, *prefix: list[str]):
        "Handler that forwards to the remote server"
        await anyio.sleep(1)
        srv = self.server.server_link(self.name)[1]
        if isinstance(srv, ClientStub):
            raise RuntimeError("Client dropped, try later")
        rcmd.extend((self.client,"cl"))
        return await srv.handle(msg,rcmd)
    
    async def aclose(self):
        pass


class Server(MsgHandler):
    """
    This is the main MoaT-Link server. It manages connections to the MQTT server,
    the clients, and (optionally) logs all changes to a file.

    Args:
      name (str): the name of this MoaT-Link server instance.
        It **must** be unique.
      cfg: configuration.
        See ``_cfg.yaml`` for default values.
        The relevant part is the ``link.server`` sub-dict (mostly).
      init (Any):
        The initial content of the root entry. **Do not use this**, except
          when setting up an entirely new MoaT-Link cluster.

    """

    # pylint: disable=no-member # mis-categorizing cfg as tuple
    data: Node
    name: str
    backend:Backend

    cfg: attrdict

    service_monitor: Broadcaster[Message]
    write_monitor: Broadcaster[Tag | tuple[Path, Any, MsgMeta]]

    logger: logging.Logger

    last_auth: str | None = None
    cur_auth: str

    _syncing: dict[str,anyio.abc.CancelScope]
    _writing: set[str]
    _writing_done: anyio.Event
    _stopped: anyio.Event

    # Client ID > disconnect error
    _error_cache: dict[str, Exception|str]

    # call to log errors
    _err_log: Callable[tuple[Path,Any,MsgMeta],Awaitable]|None = None
    _err_task: anyio.CancelScope=None

    _stamp_in: int = 0
    _stamp_out: int = 0
    _stamp_in_evt: anyio.Event

    _ping_history:Sequence[str] = ()

    _server_link:dict[str,tuple[anyio.CancelScope,BasicLink]]
    _server_link_add:anyio.Event

    _f_load:anyio.Path|None=None
    _f_save:anyio.Path|None=None

    _downed:dict[str,float]

    def __init__(self, cfg: dict, name: str, init: Any = NotGiven, load:anyio.Path|FSPath|str|None=None, save:anyio.Path|FSPath|str|None=None):
        self.data = Node()
        self.name = name
        self.cfg = to_attrdict(cfg)

        self._init = init

        self.logger = logging.getLogger("moat.link.server." + name)
        self._writing = set()
        self._writing_done = anyio.Event()
        self._error_cache = {}
        self._stamp_in_evt = anyio.Event()
        self._syncing = {}
        self._server_link = {}
        self._server_link_add = anyio.Event()
        self._downed = {}

        # connected clients
        self._clients: dict[str,ServerClient|ClientStub] = dict()

        if load is not None:
            self._f_load = anyio.Path(load)
        if save is not None:
            self._f_save = anyio.Path(save)

    @property
    def clients(self) -> dict[str,ServerClient]:
        return self._clients
    
    def server_link(self,name):
        return self._server_link[name]

    def rename_client(self, client:ServerClient, name:str):
        """
        Change a client name (result of protocol startup)
        """
        # Warning, this must not be called after a client has been announced
        if client.name == name:
            return
        if name in self._clients:
            raise ValueError(f"Name exists: {name!r}")
        del self._clients[client.name]
        client.name = name
        self._clients[name] = client


    def refresh_auth(self):
        """
        Generate a new access token (but remember the previous one)
        """
        try:
            self.last_auth = self.cur_auth
        except AttributeError:
            self.last_auth = None
        self.cur_auth = gen_ident(20)

    @property
    def tokens(self):
        res = [self.cur_auth]
        if self.last_auth is not None:
            res.append(self.last_auth)
        return res

    def maybe_update(self, path:Path, data:Any, meta:MsgMeta, local:bool=False):
        """
        A data item arrives.

        Update our store if it's newer.
        """
        if len(path) and path[0]=="run":
            return False
        if res := self.data.set(path, data, meta):  # noqa:SIM102
            if not local:
                self.write_monitor((path, data, meta))
        return res

    async def _mon_run(self, topic:Path, msg:Message) -> bool:
        """
        Messages to run.* are skipped by the main monitor backend.
        """
        return False

    async def _backend_monitor(
        self,
        task_status: anyio.abc.TaskStatus = anyio.TASK_STATUS_IGNORED,
    ):
        """
        The task that listens to the backend's message stream and updates
        the data store.

        If there is a method named ``_mon_{topic[0]}`` it is called with
        the topic and message.

        Further processing will be inhibited if the result is `False`.
        """
        t_start = anyio.current_time() if self.data else None

        async with self.backend.monitor(
            P(":R"),
            raw=False,
            qos=QoS.AT_LEAST_ONCE,
            no_local=True,
            subtree=True,
        ) as stream:
            task_status.started()
            async for msg in stream:
                self.logger.debug("Recv: %r", msg)
                msg.meta.source = "Mon"
                topic = msg.topic[1:]
                if len(topic) and topic[0] == "run":
                    continue
                path = Path.build(topic)

                if topic and (hdl := getattr(self,"_mon_{topic[0]}", None)) is not None:
                    if (await hdl(path, msg)) is False:
                        continue

                if t_start is not None and not topic:
                    if anyio.current_time()-t_start > 10:
                        t_start=None
                    elif self.data and msg.data != self.data.data:
                        raise RuntimeError(f"Existing data? {msg} {self.data}")

                self.maybe_update(path, msg.data, msg.meta)


    async def _backend_sender(self, task_status: anyio.abc.TaskStatus = anyio.TASK_STATUS_IGNORED):
        rdr = self.write_monitor.reader(999)
        task_status.started()
        async for msg in rdr:
            if isinstance(msg, Tag):
                continue
            p, d, m = msg
            if not m.source:
                m.source = '?'
            elif m.source == "Mon" or m.source[0] == "_":
                continue
            await self.backend.send(topic=P(":R") + p, data=d, meta=m, retain=(len(p) == 0 or p[0] != "run"))

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
            T(self.backend, P(":R.run.service.main.ping")),
            name=self.name,
            cfg=self.cfg.server.ping,
            send_raw=True,
        ) as actor:
            self._actor = actor
            task_status.started()

            async for msg in actor:
                self.logger.debug("ACT IN %s", repr(msg))

                if isinstance(msg, RecoverEvent):
                    self._tg.start_soon(
                        self.recover_split,
                        msg.prio,
                        msg.replace,
                        msg.local_nodes,
                        msg.remote_nodes,
                    )

                elif isinstance(msg, GoodNodeEvent):
                    # self._tg.start_soon(self.fetch_data, msg.nodes)
                    await actor.set_value(True)
                    ready.set()

                elif isinstance(msg, TagEvent):
                    # We're "it"
                    await self.set_main_link()
                    await actor.set_value(True)
                    ready.set()

                elif isinstance(msg, PingEvent):
                    # record history, for recovery
                    if msg.msg.node == self.name:
                        continue
                    await actor.set_value(True)
                    ready.set()
                    self._ping_history = msg.msg.history

    async def set_main_link(self):
        await self.backend.send(
            P(":R.run.service.main.conn"),
            {"node": uname().node, "link": self.link_data, "auth": {"token": self.cur_auth}},
            meta=MsgMeta(origin=self.name),
            retain=True,
        )

    def new_stamp(self):
        """
        Return the next stamp value.

        Usage: a client calls this via `i_stamp`, sends the value to the
        server's ``stamp`` MQTT channel, then calls `wait_stamp` to ensure
        that the stamp value arrived there.

        This ensures (absent packet loss, interrupted connections, and
        similar nonsense) that updates have arrived at the server.
        """
        self._stamp_out += 1
        return self._stamp_out

    async def wait_stamp(self, stamp):
        """
        Wait until the server has seen this stamp value (or better) on its
        ``stamp`` channel.
        """
        while self._stamp_in < stamp:
            await self._stamp_in_evt.wait()

    async def fetch_data(self, nodes):
        """
        We are newly started and don't have any data.

        Try to get the initial data from some other node.
        """
        nodes  # noqa:B018  # pyright:ignore

    async def recover_split(self, prio, replace, local_history, sources):
        """
        Recover from a network split.

        TODO
        """
        # TODO
        # The idea is:
        #  connect to a source
        #  get all its data changed since timestamp-that-source-was-last-seen
        #  re-broadcast all data changed since timestamp-that-source-was-last-seen

    async def set_error(self, path:Path, err:str|BaseException|None|NotGiven, kw:dict[str,Any], meta:MsgMeta):
        """
        Update error data.
        """
        p = Path("error")+path
        try:
            dt = self.data.get(p, create=False if err is None else None)
        except KeyError:
            return  # no error exists
        if (dd := dt.data_) is NotGiven:
            dd = {}
        elif not isinstance(dd,dict):
            dd = {"_data":dd}
        dd.update(kw)

        if err is None:
            # Delete, i.e. write the old record to error storage.
            dd["_ok"] = True
        elif err is not NotGiven:
            # count
            dd["_n"] = dd.get("_n",0)+1


        if self._err_log is not None:
            await self._err_log(path,dd,meta)

        if err is None:
            dd = NotGiven
        else:
            dd.pop("_bt", None)

        # this shortcuts maybe_update
        # forcing is required because we just modified the dict in-place
        if dt.set(..., dd, meta, force=True):
            self.write_monitor((p, dd, meta))


    async def _save(
        self,
        writer: Callable[[Tag | list[Any]], Awaitable[None]],
        shorter: PathShortener,
        hdr: bool | Tag = True,
        ftr: bool | Tag = True,
        prefix=P(":"),
        **kw,
    ):
        """Save the current state.

        @hdr and @ftr are items to prepend/append to the data stream.

        If @timestamp is set, older items will be ignored.

        @writer is an async callback that writes each item.
        """

        async def saver(path, data) -> None:
            if data.data_ is NotGiven and data.meta is None:
                return
            d, p = shorter.short(path)
            await writer([d, p, data.data_, *data.meta.dump()])
            return

        if hdr:
            if hdr is True:
                kw["state"] = self.get_state()
                hdr = self.gen_hdr_start(**kw)
            await writer(hdr)

        # await writer({"info": msg})
        await self.data.get(prefix).walk(saver, timestamp=kw.get("timestamp", 0))

        if ftr:
            if ftr is True:
                ftr = self.gen_hdr_stop()
            await writer(ftr)

    def gen_hdr_start(self, name, mode="full", **kw):
        """Return the CBOR tag for a start-of-file record"""
        from moat.util.cbor import gen_start

        fn = anyio.Path(name).name
        mstr = f"MoaT-Link {mode} {fn!r}"
        mstr += " " * (25 - len(mstr))
        kw["mode"] = mode
        kw["name"] = name
        kw["time"] = datetime.now(UTC)

        return gen_start(mstr, **kw)

    def gen_hdr_stop(self, **kw):
        """Return the CBOR tag for an end-of-file record"""
        from moat.util.cbor import gen_stop

        kw["time"] = datetime.now(UTC)
        return gen_stop(**kw)

    def gen_hdr_change(self, **kw):
        """Return the CBOR tag that describes a change"""
        from moat.util.cbor import gen_change

        kw["time"] = datetime.now(UTC)
        return gen_change(**kw)

    def get_state(self):
        return dict()

    async def save(self, path: str|anyio.Path, task_status=anyio.TASK_STATUS_IGNORED, **kw):
        """Save the current state to ``path``."""
        shorter = PathShortener([])
        try:
            spath = str(path)
            if spath in self._writing:
                raise RuntimeError(f"Already writing: {spath!r}")
            self._writing.add(spath)
            async with MsgWriter(path=path, codec="std-cbor") as mw:
                task_status.started()
                await self._save(mw, shorter, name=str(path), mode="full", **kw)
        finally:
            self._writing.remove(spath)

    async def save_stream(
        self,
        path: str | anyio.Path | FSPath | None = None,
        save_state: bool = False,
        task_status=anyio.TASK_STATUS_IGNORED,
        **kw,
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
            spath=str(path)
            try:
                if spath in self._writing:
                    raise RuntimeError(f"Already writing: {spath!r}")
                self._writing.add(spath)
                rdr = self.write_monitor.reader(999)
                async with (
                    anyio.create_task_group() as tg,
                    MsgWriter(path=path, codec="std-cbor") as mw,
                ):
                    try:
                        msg = self.gen_hdr_stop(
                            name=str(path),
                            mode="restart" if save_state else "next",
                        )
                        # This ensures that the Stop message isn't seen by
                        # the new writer
                        self.write_monitor(msg)
                        rdr = self.write_monitor.reader(999, send_last=False)
                        task_status.started(scope)

                        msg = self.gen_hdr_start(
                            name=str(path),
                            mode="full" if save_state else "incr",
                            state=None if save_state else False,
                            **kw,
                        )
                        try:
                            await mw(msg)
                        except Exception as exc:
                            self.logger.error("MSG WRITE FAIL %r", msg, exc_info=exc)
                            msg = self.gen_hdr_start(
                                name=str(path),
                                mode="full" if save_state else "incr",
                                state=None if save_state else False,
                            )
                            await mw(msg)


                        if save_state:
                            tg.start_soon(
                                partial(
                                    self._save,
                                    mw,
                                    shorter,
                                    hdr=False,
                                    ftr=self.gen_hdr_change(state=False),
                                ),
                            )

                        await self._save_stream(rdr, mw, shorter, msg)
                    except BaseException as exc:
                        #
                        with anyio.move_on_after(2, shield=True):
                            await mw(self.gen_hdr_stop(mode="error", error=repr(exc)))
                        raise

                    finally:
                        with anyio.move_on_after(2, shield=True):
                            await mw.flush(force=True)
            finally:
                self._writing.remove(spath)
                self._writing_done.set()

    async def save_errstream(
        self,
        path: str | anyio.Path | FSPath | None = None,
        save_state: bool = False,
        *,
        task_status=anyio.TASK_STATUS_IGNORED,
    ):
        """Save the current error log to ``path``.
        Continue writing until cancelled.

        Args:
          path: The file to save to.
          save_state: Flag whether to write the current state.
            If ``False`` (the default), only write changes.

        """
        shorter = PathShortener([])

        async with MsgWriter(path=path, codec="std-cbor") as mw:
            try:
                msg = self.gen_hdr_start(
                    name=str(path),
                    mode="error",
                    state=None if save_state else False,
                )
                await mw(msg)

                task_status.started()

                async def cmd(p,d,m):
                    n,p = shorter.short(p)
                    await mw((n,p,d,*m.dump()))

                with anyio.CancelScope() as scope:
                    if save_state:
                        await self._save( mw, shorter, hdr=False,
                                ftr=self.gen_hdr_change(state=False,mode="error"),
                                path=Path("error"),
                        )

                    if self._err_task is not None:
                        self._err_task.cancel()
                    try:
                        self._err_task = scope
                        self._err_log = cmd
                        await anyio.sleep_forever()
                    finally:
                        if self._err_task is scope:
                            self._err_task = None
                            self._err_log = None

            except anyio.get_cancelled_exc_class():
                with anyio.move_on_after(2, shield=True):
                    await mw(self.gen_hdr_stop(mode="cancel"))
                raise

            except BaseException as exc:
                #
                with anyio.move_on_after(2, shield=True):
                    await mw(self.gen_hdr_stop(mode="error", error=repr(exc)))
                raise

            finally:
                with anyio.move_on_after(2, shield=True):
                    await mw.flush(force=True)

    @staticmethod
    async def _save_stream(rdr, mw, shorter, ign):
        # helper for .save_stream() to keep the indent levels down

        last_saved = time.monotonic()
        last_saved_count = 1
        TIMEOUT = 5
        MAXMSG = 100

        while True:
            msg = None
            if last_saved_count:
                with anyio.move_on_after(TIMEOUT):
                    msg = await anext(rdr)
            else:
                msg = await anext(rdr)
            if msg is None or msg is ign:
                pass
            elif isinstance(msg, (list, tuple)):
                path, data, meta = msg
                if len(path) and path [0]=="run":
                    continue
                d, p = shorter.short(path)
                await mw([d, p, data, *meta.dump()])
                last_saved_count += 1
            elif isinstance(msg, Tag) and msg.tag == CBOR_TAG_MOAT_FILE_END:
                await mw(msg)
                return
            else:
                await mw(msg)

            # Ensure that we save the system state often enough.
            t = time.monotonic()
            td = t - last_saved
            if td >= TIMEOUT or last_saved_count >= MAXMSG:
                await mw.flush(force=True)
                last_saved = time.monotonic()
                last_saved_count = 0

    async def _flush_deleted(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Background task to remove deleted nodes from the tree
        """
        task_status.started()
        await anyio.sleep(self.cfg.timeout.delete / 10)
        t = time.time()

        async def _walk(d: Node) -> bool:
            # return True if we need to keep this

            has_any = False
            await anyio.sleep(0.1)

            # Drop the Meta entry if the deletion was long enough ago
            if (
                d._data is NotGiven  # noqa:SLF001
                and d.meta is not None
                and t - d.meta.timestamp > self.cfg.timeout.delete
            ):
                del d.meta
            drop = set()
            for k, v in d.items():
                if await _walk(v):
                    has_any = True
                else:
                    drop.add(k)
            for k in drop:
                del d[k]
            if has_any or d._data is not NotGiven:  # noqa:SLF001
                return True
            return d.meta is not None

        while True:
            await _walk(self.data)

            await anyio.sleep(self.cfg.timeout.delete / 20)

    async def _save_task(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Background task to periodically restart the saver task
        """
        save = self.cfg.server.save
        dest = anyio.Path(save.dir)
        rewrite = 0
        kw={}
        while True:
            now = datetime.now(UTC)
            fn = dest / now.strftime(save.name)
            await fn.parent.mkdir(exist_ok=True, parents=True)
            await self.run_saver(path=fn, save_state=rewrite==0, **kw)
            
            task_status.started()
            task_status = anyio.TASK_STATUS_IGNORED

            await anyio.sleep(save.interval)
            rewrite = (rewrite or save.rewrite)-1
            kw["prev"]=str(fn)


    async def run_saver(self, path: PathType|None, save_state: bool = True, **kw):
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
        if path is not None:
            await self._tg.start(
                partial(
                    self.save_stream,
                    path=path,
                    save_state=save_state,
                    **kw,
                ),
            )
        else:
            self.write_monitor(self.gen_hdr_stop(reason="log_end"))

    async def run_errsaver(self, path: PathType|None, save_state: bool = True):
        """
        Start a task that logs errors.

        At most one one saver runs at a time; if a new one is started,
        the old saver is cancelled as soon as the new saver's current state
        is on disk (if told to do so) and it is ready to start writing.

        Args:
          path (str): The file to save to. If ``None``, simply stop any
            already-running error log.
          save_state (bool): Flag whether to write the current state.
            If `False` (the default), only write changes.

        """
        if path is not None:
            await self._tg.start(
                partial(
                    self.save_errstream,
                    path=path,
                    save_state=save_state,
                ),
            )
        elif self._err_task is not None:
            self._err_task_cancel()

            self._err_task = None
            self._err_log = None


    async def _sigterm(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        with anyio.open_signal_receiver(signal.SIGTERM) as r:
            task_status.started()

            async for _s in r:
                self._stop_flag.set()
                break

    async def serve(
        self,
        *,
        task_status=anyio.TASK_STATUS_IGNORED,
    ) -> None:
        """
        The method that opens a backend connection and actually runs the server.

        This will terminate when `stop` is called (in another task).
        """
        will_data = attrdict(
            topic=P(":R.run.service.main.server")/self.name,
            data=NotGiven,
            qos=1,
            retain=True,
        )

        # root path
        csr = self.cfg.root
        csr = P(csr) if isinstance(csr, str) else Path.build(csr)
        Root.set(csr)

        self._stop_flag = anyio.Event()
        self._stopped = anyio.Event()

        async with (
            EventSetter(self._stopped),
            Broadcaster(send_last=True, length=1000) as self.write_monitor,
            get_backend(self.cfg, name=self.name, will=will_data) as self.backend,
            anyio.create_task_group() as _tg,
        ):
            self._tg = _tg

            # Semi-detached taskgroups for clients and listeners

            async def run_tg(task_status):
                async with anyio.create_task_group() as tg:
                    task_status.started(tg)
                    await anyio.sleep_forever()

            self.logger.info("Starting up.")
            client_tg = await _tg.start(run_tg)
            listen_tg = await _tg.start(run_tg)

            # basic infrastructure

            await _tg.start(self._auth_update)
            await _tg.start(self._sigterm)

            # monitor client connects
            await _tg.start(self._watch_client)

            # background tasks

            await _tg.start(self._backend_monitor)
            await _tg.start(self._backend_sender)
            await _tg.start(self._read_main)
            await _tg.start(self._read_stamp)

            # create a client link to any other servers we see
            await _tg.start(self._watch_up)

            # retrieve data

            self.logger.info("Reading data.")
            await _tg.start(self._read_initial)

            # Log errors
            if "errlog" in self.cfg.server:
                await _tg.start(self.save_errstream, self.cfg.server.errlog, True)

            # save data
            self.logger.info("Starting services.")

            sd = anyio.Path(self.cfg.server.save.dir)
            if await sd.is_dir():
                await _tg.start(self._save_task)

            if self._init is not NotGiven:
                self.maybe_update(Path(), self._init, MsgMeta(origin="INIT",source="INIT"))

            if self._f_save is not None:
                await _tg.start(self.save, self._f_save)
                self._f_save=None

            # let clients in
            # TODO config via database

            ports = []
            if "ports" in self.cfg.server:
                for name, conn in self.cfg.server.ports.items():
                    ports.append(await listen_tg.start(self._run_server, client_tg, f"{self.name}-{name}", conn))
            if not ports:
                conn = attrdict(host="0.0.0.0",port=self.cfg.server.port)
                ports.append(await listen_tg.start(self._run_server, client_tg, self.name, conn))

            globals = {"0.0.0.0","::"}
            link = [ {"host": _get_my_ip(hp[0] == "::") if hp[0] in globals else hp[0], "port": hp[1]} for hp in ports if isinstance(hp,tuple) ]

            if not link:
                self.logger.warning("No external port")
            self.link_data = link

            # announce us to clients
            self.logger.info("Announcing to clients.")

            await self.backend.send(
                P(":R.run.service.main.server")/self.name,
                {"node": uname().node, "link": self.link_data, "auth": {"token": self.cur_auth}},
                meta=MsgMeta(origin=self.name),
                retain=True,
                qos=1,
            )

            ping_ready = anyio.Event()
            await _tg.start(self._pinger, ping_ready)
            if self._init is not NotGiven:
                await self.set_main_link()
            elif self.cfg.server.timeout.up > 0:
                with anyio.move_on_after(self.cfg.server.timeout.up):
                    await ping_ready.wait()
            elif self.cfg.server.timeout.up < 0:
                with anyio.fail_after(-self.cfg.server.timeout.up):
                    await ping_ready.wait()

            # watch for Will messages from dying servers that are "it"
            await _tg.start(self._watch_down)

            del self._init  # after this point there's no more difference

            # done, ready for service

            task_status.started((self, ports))
            self.logger.info("Start done.")

            # maintainance

            await _tg.start(self._flush_deleted)

            # wait for some stop signal

            await self._stop_flag.wait()


            # announce that we're going down
            await self.backend.send(
                topic=P(":R.run.service.main.down"),
                data=self.name,
                retain=False,
            )
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

    async def cancel(self):
        """Cancel the server task.

        Unlike `stop` this does not allow the server to shut down cleanly.
        """
        self._tg.cancel_scope.cancel()  # pyright:ignore  # ??

    async def stop(self):
        """
        Tell the server to shut down cleanly.

        Waits until the server is in fact down.
        """
        self._stop_flag.set()
        await self._stopped.wait()

    async def _auth_update(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Background task to refresh the auth data.
        """
        self.refresh_auth()
        task_status.started()
        while True:
            await anyio.sleep(900)
            self.refresh_auth()

            await anyio.sleep(30)
            self.last_auth = None

    async def _run_server_link(self,name,data, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Run a single client link to another server.
        """
        # TODO: There should be only one TCP link between server A and B, not two
        # (plus another for syncing).

        backoff=0

        with anyio.CancelScope() as sc:
            self._server_link[name] = (sc,None)
            task_status.started()

            while True:
                try:
                    async with BasicLink(self.cfg, self.name, data, is_server=True) as conn:
                        conn.add_sub("cl")
                        if self._server_link[name][0] is not sc:
                            return
                        self._server_link[name] = (sc,conn)
                        self._server_link_add.set()
                        self._server_link_add = anyio.Event()

                        async with anyio.create_task_group() as tg:
                            # ask it about its existing clients
                            async with conn.cl().stream_in() as cld:
                                async for cl in cld:
                                    cl = cl[0]
                                    if cl == name or cl == self.name:
                                        continue
                                    if not isinstance(self.clients.get(cl,None), ServerClient):
                                        self._clients[cl] = ClientStub(self,name,cl)

                            await anyio.sleep(30)
                            backoff=0
                            await anyio.sleep_forever()

                except* (EOFError,anyio.ClosedResourceError,anyio.EndOfStream):
                    self.logger.warning("Link to %s closed", name)

                except* EnvironmentError:
                    self.logger.warning("Link to %s died", name)

                except* Exception as exc:
                    self.logger.warning("Link to %s died", name, exc_info=exc)

                finally:
                    if name in self._server_link and self._server_link[name][0] is sc:
                        self._server_link[name] = (sc,None)
                    else:
                        return

                backoff = min(backoff*1.2+.1,30)
                await anyio.sleep(backoff)



    async def _watch_client(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Monitor fixed-name client announcements.
        """
        async with self.backend.monitor(
            P(":R.run.service.main.client"),
            raw=False,
            qos=QoS.AT_LEAST_ONCE,
            no_local=True,
            subtree=True,
        ) as mon:
            task_status.started()

            async for msg in mon:
                name = msg.topic[-1]
                rem = self._clients.get(name,None)
                if msg.data is NotGiven:
                    if rem is None:
                        continue
                    if not isinstance(rem, ClientStub) or rem.name != msg.meta.origin:
                        raise ValueError(repr(rem))  # XXX
                        continue
                    del self._clients[name]
                else:
                    if isinstance(rem,ServerClient):
                        # we have this connection, so don't listen to them
                        continue
                    if name == msg.data:
                        self.logger.warning("Got self-ref client: %r %r", name,msg.data)
                        continue
                    self._clients[name] = ClientStub(self,msg.data,name)


    async def _watch_up(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Monitor servers' service announcements and connects to them
        so that client links can be forwarded.
        """
        async with (
            anyio.create_task_group() as tg,
            self.backend.monitor(P(":R.run.service.main.server"), subtree=True) as mon,
        ):
            task_status.started()
            async for msg in mon:
                name = msg.topic[-1]

                sl = self._server_link.pop(name,None)
                if sl is not None:
                    sl[0].cancel()

                if msg.data is NotGiven:
                    tg.start_soon(self._down_one,name)
                    continue
                self._downed.pop(name,None)

                if name == self.name:
                    continue
                if name in self._server_link:
                    continue
                await tg.start(self._run_server_link,name,msg.data)

    async def _down_one(self, name:str):
        # protect against repeats
        t = anyio.current_time()
        if name in self._downed and t-self._downed[name] < self.cfg.server.ping.cycle:
            return
        self._downed[name] = t

        main = aiter(self.service_monitor.reader(5, send_last=True))
        try:
            with anyio.fail_after(0.1):
                service = await anext(main)
        except TimeoutError:
            return  # no service, nothing to do
        if service.meta.origin != name:
            return  # not current

        async with anyio.create_task_group() as tg:
            @tg.start_soon
            async def changed():
                async for msg in main:
                    if msg.meta.origin != name:
                        tg.cancel_scope.cancel()
                        return

            gap = self.cfg.server.ping.gap
            try:
                n = self._ping_history.index(self.name)
            except ValueError:
                await anyio.sleep(gap*(1.2+random.random()))
            else:
                await anyio.sleep(gap*n/len(self._ping_history))
            await self.set_main_link()


    async def _watch_down(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Monitor "down" messages and broadcast our own info if it's the active node.
        """

        async with (
                self.backend.monitor(P(":R.run.service.main.down")) as mon,
                anyio.create_task_group() as tg,
            ):
            task_status.started()
            async for msg in mon:
                name = msg.data
                if name == self.name:
                    return
                tg.start_soon(self._down_one,msg.data)

    async def _read_main(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Task to read the main service monitoring channel
        """
        async with (
            Broadcaster(300, send_last=True) as self.service_monitor,
            self.backend.monitor(P(":R.run.service.main.conn")) as mon,
        ):
            task_status.started()
            async for msg in mon:
                self.service_monitor(msg)

    async def _read_stamp(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Task to read our stamping channel
        """
        async with self.backend.monitor(P(":R.run.service.main.stamp")/self.name) as mon:
            task_status.started()
            async for msg in mon:
                self._stamp_in = msg.data
                self._stamp_in_evt.set()
                self._stamp_in_evt = anyio.Event()

    async def _sync_from(self, name: str, data: dict) -> bool:
        """
        Sync from the server indicated by this message.

        Returns True if successful.
        """
        with anyio.CancelScope() as scope:
            if name in self._syncing:
                self.logger.warning("Already syncing to %s", name)
                return False
            self._syncing[name] = scope

            try:
                with anyio.fail_after(5):
                    while name not in self._server_link or (conn := self._server_link[name][1]) is None:
                        await self._server_link_add.wait()

                await self._sync_one(conn)
            except OSError as exc:
                self.logger.warning(
                    "No sync %r: %r",
                    data,
                    exc,
                )
                return False
            except Exception as exc:
                self.logger.warning(
                    "No sync %r: %r",
                    data,
                    exc,
                    exc_info=exc,
                )
                return False
            finally:
                del self._syncing[name]
        return True

    async def _sync_one(self, conn: MsgSender, prefix: Path = Path()):
        async with conn.cmd(P("d.walk"), prefix).stream_in() as feed:
            pl = PathLongener()
            upd = 0
            skp = 0
            async for msg in feed:
                d, p, data, *mt = msg
                path = pl.long(d, p)
                meta = MsgMeta.restore(mt)  # noqa:SLF001
                meta.source = "_Load"
                if self.maybe_update(prefix + path, data, meta):
                    upd += 1
                else:
                    skp += 1
                self.logger.debug("Sync Msg %r", msg)
        self.logger.info("Sync finished. %d new, %d existing", upd, skp)

    async def _load_initial(self, fn):
        upd,skp,tags = await self.load_file(fn=self._f_load)
        if not upd:
            raise RuntimeError("No data!")
        if not tag_check(tags):
            raise RuntimeError("No or incomplete tags!")
        return

    async def _read_initial(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Read initial data from either file backup or a remote server.

        Runs in the background if we have initial data.
        """
        ready = anyio.Event()
        if self._init is not NotGiven:
            ready.set()
        if self._f_load is not None:
            await self._load_initial(self._f_load)
            task_status.started()
            return

        async with anyio.create_task_group() as tg:
            @tg.start_soon
            async def trigger():
                with anyio.fail_after(self.cfg.server.timeout.startup):
                    await ready.wait()
                task_status.started()

            tg.start_soon(self._get_remote_data, aiter(self.service_monitor), ready)
            tg.start_soon(self._read_saved_data, ready)

            # Allow for retrieving data from MQTT if no server is running.
            # This should not be done lightly.
            if self.cfg.server.timeout.mqtt:
                rdr = self.write_monitor.reader(10000)
                while True:
                    with anyio.move_on_after(self.cfg.server.timeout.mqtt):
                        await anext(rdr)
                        continue
                    break
                ready.set()

    async def _read_saved_data(self, ready: anyio.Event):
        save = self.cfg.server.save
        dest = anyio.Path(save.dir)
        if not await dest.is_dir():
            self.logger.info("No saved data in %r", str(dest))
            return

        done=set()
        fs = []
        async for p, _d, f in dest.walk():
            for ff in f:
                if ff.endswith(".moat"):
                    fs.append(p / ff)
        fs.sort()
        fn=None

        tupd = 0
        while fs:
            if fn is None:
                fn = fs.pop()

            sfn = str(fn)
            if sfn in done or sfn in self._writing:
                fn = None
                continue
            done.add(sfn)

            try:
                upd,skp,tags = await self.load_file(fn=fn)
            except Exception as exc:
                self.logger.error("Failed to load %s",fn,exc_info=exc)
                await fn.rename(fn.with_suffix(".moat.bad"))
                continue

            if not upd or not tags:
                continue
            if not tag_check(tags):
                # extract the first tag's value
                tt = tags[0]
                while isinstance(tt,Tag):
                    tt=t=tt.value
                if isinstance(tt,Sequence):
                    tt=tt[1]
                fn=tt.get("prev",None)
                if fn is not None:
                    fn = anyio.Path(fn)
                continue
            ready.set()
            return


    async def load_file(self, fn:anyio.Path, prefix:Path=Path(), local:bool=False) -> tuple[int,int,list[Tag]]:
        """
        Load a file.

        The result is the number of updated/skipped entries,
        plus the tags from the file.
        """
        self.logger.info("Loading from %r", fn)
        async with MsgReader(fn, codec="std-cbor") as rdr:
            pl = PathLongener(prefix)
            upd, skp, tags = 0, 0, []
            ehdr = None
            async for msg in rdr:
                self.logger.debug("Load %r",msg)
                if isinstance(msg, Tag) and msg.tag == CBOR_TAG_CBOR_LEADER:
                    msg = msg.value  # noqa:PLW2901
                if isinstance(msg, Tag):
                    tags.append(msg)
                    if msg.tag == CBOR_TAG_MOAT_FILE_ID:
                        # concatenated files?
                        if ehdr is not None:
                            raise ValueError("START within file %r", str(fn))
                        # TODO verify that these belong together

                    elif msg.tag == CBOR_TAG_MOAT_CHANGE:
                        # TODO verify?
                        continue

                    elif msg.tag == CBOR_TAG_MOAT_FILE_END:
                        if ehdr is None:
                            raise ValueError("END without start in %r", str(fn))
                            raise ValueError("Duplicate END in %r", str(fn))
                    else:
                        self.logger.warning("Unknown tag %r", str(fn), msg)
                        continue
                    ehdr = msg
                    continue
                elif ehdr is None:
                    raise ValueError("Untagged file")
                elif ehdr.tag != CBOR_TAG_MOAT_FILE_ID:
                    raise ValueError("Data %r after tag: %r", msg, ehdr)

                # Any other problems just raise the exception
                d, p, data, *mt = msg
                path = pl.long(d, p)
                meta = MsgMeta.restore(mt)  # noqa:SLF001
                meta.source = "_file"
                if self.maybe_update(path, data, meta, local=local):
                    # Entries that have been deleted don't count as updates
                    if data is not NotGiven:
                        upd += 1
                else:
                    skp += 1

            self.logger.info("Loading from %r done: %d/%d", fn,upd,skp)
            return upd, skp, tags

    async def _get_remote_data(self, main: BroadcastReader, ready: anyio.Event):
        seen = defaultdict(lambda: 0)
        async for msg in main:
            if msg.meta.origin == self.name:
                continue  # XXX stale
            if msg.data is NotGiven:
                continue  # deleted?
            if await self._sync_from(msg.meta.origin, msg.data):
                ready.set()
                return
            sn = seen[msg.meta.origin]
            if sn > 2:
                return
            seen[msg.meta.origin] = sn + 1

        pass

    def get_cached_error(self, name) -> Exception|str|None:
        return self._error_cache.pop(name, None)

    async def _run_server(self, tg, name, cfg, *, task_status=anyio.TASK_STATUS_IGNORED):
        """runs a listener on a single port"""
        if "host" in cfg:
            # TODO SSL and/or whatnot
            lcfg = attrdict()
            if "host" in cfg:
                lcfg.local_host = cfg.host
            if "port" in cfg:
                lcfg.local_port = cfg.port
            try:
                listener = await anyio.create_tcp_listener(**lcfg)
            except Exception as exc:
                raise RuntimeError("Could not create socket", cfg) from exc

        elif "port" in cfg:
            # Unix socket
            port = cfg.port
            if port.startswith("RUN/"):
                port = os.environ["XDG_RUNTIME_DIR"]+port[3:]
            try:
                listener = await anyio.create_unix_listener(port)
            except Exception as exc:
                raise RuntimeError("Could not create socket", port, cfg) from exc

        else:
            self.logger.error("No host/port in server cfg %s: %r",name,cfg)
            task_status.started(None)
            return

        async with listener:
            task_status.started(listener.extra(SocketAttribute.local_address))
            task_status = anyio.TASK_STATUS_IGNORED
            await listener.serve(partial(self._client_task, name), task_group=tg)


    async def _client_task(self, name, stream):
        """
        Manager for a single client connection.

        The actual work happens in `ServerClient.run`. This wrapper
        mainly tries to record what went wrong on the server so the next
        client session can ask.

        @name is the name of the link.
        """
        c = None
        cnr = -1
        try:
            c = ServerClient(server=self, prefix=name, stream=stream)
            cnr = c.client_nr
            try:
                oc = self._clients.get(c.name,None)
                self._clients[c.name] = c
                if oc is not None:
                    await oc.aclose()
                    del oc
                await c.run()

            finally:
                if self._clients.get(c.name,None) is c:
                    del self._clients[c.name]

                    if not c.is_server and "." not in c.name:
                        # announce that client vanished
                        # The condition *must* match the announcement
                        with anyio.move_on_after(2,shield=True):
                            await self.backend.send(P(":R.run.service.main.client")/c.name,b'',codec=None,retain=True)
        except (ClosedResourceError, anyio.EndOfStream):
            self.logger.debug("XX %d closed", cnr)
        except BaseException as exc:
            CancelExc = anyio.get_cancelled_exc_class()
            if hasattr(exc, "split"):
                exc = exc.split(CancelExc)[1]  # pyright: ignore
                ex = list(exc_iter(exc))
                if len(ex) == 1:
                    exc = ex[0]
            elif hasattr(exc, "filter"):
                exc = exc.filter(lambda e: None if isinstance(e, CancelExc) else e, exc)  # pyright: ignore

            if exc is not None and not isinstance(exc, CancelExc):
                if isinstance(exc, (ClosedResourceError, anyio.EndOfStream)):
                    self.logger.debug("Client %s closed", cnr)
                elif isinstance(exc, TimeoutError):
                    self.logger.warning("Client %s timed out", cnr)
                else:
                    self.logger.exception("Client connection %s killed", cnr, exc_info=exc)
            if exc is None:
                exc = "Cancelled"
            self._error_cache[name] = cast(Exception,exc)
            self.logger.debug("XX END XX %s", cnr)

        finally:
            with anyio.move_on_after(2, shield=True):
                await stream.aclose()


    # server-to-server crosslinks

    async def sub_cl(self, msg: Msg, rcmd: list) -> None:
        "Local subcommand redirect for 'cl'"
        if rcmd:
            cl = self.clients[rcmd.pop()]
            return await cl.sender.handle(msg,rcmd)
        raise RuntimeError("Should have streamed")

    async def stream_cl(self, msg:Msg) -> None:
        """
        Send the list of currently-known clients.
        """
        cl = list(self.clients)
# disabled
#       if msg.args:
#           srv = msg.args[0]
#           async with msg.stream_in() as ml:
#               async for mm in ml:
#                   name = mm[0]
#                   if not isinstance(self._clients.get(name,None), ServerClient):
#                       self._clients[name] = ClientStub(self,srv)
#           return
        async with msg.stream_out(len(cl)) as ml:
            for cn in cl:
                await ml.send(cn)

