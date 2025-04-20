"""
The main MoaT-Link Server
"""

from __future__ import annotations

import anyio
import logging
import signal
import time
import anyio.abc
from anyio.abc import SocketAttribute
from contextlib import asynccontextmanager, nullcontext
from datetime import UTC, datetime
from functools import partial
from asyncactor import (
    Actor,
    GoodNodeEvent,
    RecoverEvent,
    TagEvent,
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
)
from moat.lib.cmd import MsgSender
from moat.lib.cmd.anyio import run as run_cmd_anyio
from moat.lib.codec.cbor import CBOR_TAG_CBOR_LEADER, Tag
from moat.link.auth import AnonAuth, TokenAuth
from moat.link.backend import get_backend, Backend
from moat.link.client import BasicLink, LinkCommon
from moat.link.exceptions import ClientError
from moat.link.hello import Hello
from moat.link.meta import MsgMeta
from moat.link.node import Node
from moat.util.broadcast import Broadcaster, BroadcastReader
from moat.util.cbor import (
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
        self._hello = Hello(
            them=f"C_{self.client_nr}",
            me=self.name,
            me_server=True,
            auth_in=[TokenAuth("Duh"), AnonAuth()],
        )
        async with (
            anyio.create_task_group() as self.tg,
            run_cmd_anyio(self, self.stream) as cmd,
        ):
            self._sender = MsgSender(cmd)

            # basic setup
            try:
                if await self._hello.run(MsgSender(cmd)) is False or not (
                    auth := self._hello.auth_data
                ):
                    self.logger.debug("NO %s", self.client_nr)
                    return
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
        self.logger.debug("IN %s", msg)
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
        await msg.result(d.data, d.meta)

    doc_d = dict(_d="Data access commands")

    def sub_d(self, msg: Msg, rcmd: list) -> Awaitable:
        "Local subcommand redirect for 'd'"
        return self.handle(msg, rcmd, "d")

    doc_s = dict(_d="Data load/save commands")

    def sub_s(self, msg: Msg, rcmd: list) -> Awaitable:
        "Local subcommand redirect for 's'"
        return self.handle(msg, rcmd, "s")

    doc_d_list = dict(_d="get subnode child names", _r=["Any:Data", "MsgMeta"], _o="str")

    async def cmd_d_list(self, msg):
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
            d, sp = ps.short(p)
            await msg.send(d, sp, n.data, *n.meta.dump())

        d = self.server.data.get(msg[0], create=False)
        ts = msg.get(1, 0)
        xmin = msg.get(2, 0)
        xmax = msg.get(3, 9999999)
        async with msg.stream_out():
            await d.walk(_writer, timestamp=ts, min_depth=xmin, max_depth=xmax)

    doc_d_set = dict(_d="set value", _0="Path", _1="Any", _99="MsgMeta:optional")

    async def cmd_d_set(self, path, value, meta: MsgMeta | None = None):
        """Set a node's value.

        Arguments:
        * pathname
        * value
        * optional: metadata

        You should not call this. Send to the MQTT topic directly.
        """
        if meta is None:
            meta = MsgMeta(origin=self.name)
        meta.source = "Client"

        self.server.maybe_update(path, value, meta)

    doc_d_del = dict(_d="delete value", _0="Path", _1="Any", _99="MsgMeta:optional")

    async def cmd_d_del(self, msg):
        """Delete a node's value.

        Arguments:
        * pathname
        * optional: metadata
        """
        path = msg[0]
        if len(msg) > 2:
            meta = msg[2]
        else:
            meta = MsgMeta(origin=self.name)
        meta.source = "Client"

        self.server.maybe_update(path, NotGiven, meta)

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

    doc_i_log = dict(_d="start logging", _0="str:filename", state="bool:include current state")

    async def cmd_i_log(self, path: str, *, state: bool = False):
        await self.server.run_saver(path, save_state=state)
        return True

    doc_s_save = dict(_d="save current state", _0="str:filename", prefix="path:subtree")

    async def cmd_s_save(self, path: str, prefix=Path()):
        await self.server.save(path, prefix=prefix)

        return True

    doc_s_load = dict(_d="load state", _0="str:filename", prefix="path:subtree")

    async def cmd_s_load(self, path, *, prefix=Path()):
        return await self.server.load(path=path, prefix=prefix)


class Server:
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

    _error_cache: dict[str, Exception|str]

    _stamp_in: int = 0
    _stamp_out: int = 0
    _stamp_in_evt: anyio.Event

    def __init__(self, cfg: dict, name: str, init: Any = NotGiven):
        self.data = Node()
        self.name = name
        self.cfg = to_attrdict(cfg)

        if init is not NotGiven:
            self.data.set(Path(), init, MsgMeta(origin="INIT"))

        self.logger = logging.getLogger("moat.link.server." + name)
        self._writing = set()
        self._writing_done = anyio.Event()
        self._error_cache = {}
        self._stamp_in_evt = anyio.Event()
        self._syncing = {}

        # connected clients
        self._clients: set[ServerClient] = set()

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

    def maybe_update(self, path, data, meta, local:bool=False):
        """
        A data item arrives.

        Update our store if it's newer.
        """
        if res := self.data.set(path, data, meta):  # noqa:SIM102
            if not local:
                self.write_monitor((path, data, meta))
        return res

    async def _backend_monitor(
        self,
        task_status: anyio.abc.TaskStatus = anyio.TASK_STATUS_IGNORED,
    ):
        """
        The task that listens to the backend's message stream and updates
        the data store.
        """
        t_start = anyio.current_time() if self.data else None

        chop = len(self.cfg.root)
        async with self.backend.monitor(
            P(":R.#"),
            raw=False,
            qos=QoS.AT_LEAST_ONCE,
            no_local=True,
        ) as stream:
            task_status.started()
            async for msg in stream:
                self.logger.debug("Recv: %r", msg)
                topic = msg.topic[chop:]
                if topic and topic[0] == "run":
                    continue

                msg.meta.source = "Mon"
                path = Path.build(topic)
                if t_start is not None and not topic:
                    if anyio.current_time()-t_start > 10:
                        t_start=None
                    elif self.data and msg.data != self.data.data:
                        raise RuntimeError(f"Existing data? {msg} {self.data}")

                if self.maybe_update(path, msg.data, msg.meta) is False:
                    # This item from outside is stale.
                    d = self.data.get(path)
                    try:
                        data = d.data
                    except ValueError:
                        # deleted
                        await self.backend.send(
                            topic=msg.topic,
                            data=b"",
                            codec=None,
                            meta=d.meta,
                        )
                    else:
                        await self.backend.send(topic=msg.topic, data=data, meta=d.meta)

    async def _backend_sender(self, task_status: anyio.abc.TaskStatus = anyio.TASK_STATUS_IGNORED):
        rdr = self.write_monitor.reader(999)
        task_status.started()
        async for msg in rdr:
            if isinstance(msg, Tag):
                continue
            p, d, m = msg
            if m.source == "Mon" or m.source[0] == "_":
                continue
            await self.backend.send(topic=P(":R") + p, data=d, meta=m)

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
                self.logger.info("ACT IN %s", repr(msg))

                if isinstance(msg, RecoverEvent):
                    self._tg.start_soon(
                        self.recover_split,
                        msg.prio,
                        msg.replace,
                        msg.local_nodes,
                        msg.remote_nodes,
                    )

                elif isinstance(msg, GoodNodeEvent):
                    self._tg.start_soon(self.fetch_data, msg.nodes)
                    ready.set()

                elif isinstance(msg, TagEvent):
                    # We're "it"; find missing data
                    await self.set_main_link()

    async def set_main_link(self):
        await self.backend.send(
            P(":R.run.service.main"),
            {"link": self.link_data, "auth": {"token": self.cur_auth}},
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
        breakpoint()
        nodes  # noqa:B018  # pyright:ignore

    async def recover_split(self, prio, replace, local_history, sources):
        """
        Recover from a network split.
        """
        # TODO
        # The idea is:
        #  connect to a source
        #  get all its data changed since timestamp-that-source-was-last-seen
        #  re-broadcast all data changed since timestamp-that-source-was-last-seen

    async def load(
        self,
        path: str | None = None,
        stream: anyio.abc.ByteReceiveStream | None = None,
        local: bool = False,
        prefix: Path = P(":"),
    ):
        """Load data from this stream

        Args:
          @stream: The stream to read.
          @local: Flag whether this file contains initial data and thus
                  its contents shall not be broadcast. Don't set this if
                  the server is already operational.
          @prefix: load to below this prefix
        """
        longer = PathLongener(())

        upd, skp, met = 0, 0, []

        async with MsgReader(path=path, stream=stream, codec="std-cbor") as rdr:
            async for m in rdr:
                if isinstance(m, Tag) and m.tag == CBOR_TAG_CBOR_LEADER:
                    m = m.value  # noqa:PLW2901
                if isinstance(m, Tag):
                    met.append(m)
                    continue
                d, p, data, *mt = m
                path_ = longer.long(d, p)
                meta = MsgMeta._moat__restore(mt, NotGiven)  # noqa:SLF001
                meta.source = path
                if self.maybe_update(prefix + path_, data, meta, local=local):
                    upd += 1
                else:
                    skp += 1

        self.logger.debug("Loading finished.")
        return (upd, skp, met)

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

        @writer
        """

        async def saver(path, data) -> None:
            if data.data is NotGiven and data.meta is None:
                return
            d, p = shorter.short(path)
            await writer([d, p, data.data, *data.meta.dump()])
            return

        if hdr:
            if hdr is True:
                kw["state"] = self.get_state()
                hdr = self.gen_hdr_start(**kw)
            await writer(hdr)

        # await writer({"info": msg})
        await self.data[prefix].walk(saver, timestamp=kw.get("timestamp", 0))

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

        return gen_start(mstr, **kw)

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

    async def save(self, path: str | None = None, **kw):
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
        path: str | anyio.Path | FSPath | None = None,
        save_state: bool = False,
        task_status=anyio.TASK_STATUS_IGNORED,
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
                        msg = self.gen_hdr_start(
                            name=str(path),
                            mode="full" if save_state else "incr",
                            state=None if save_state else False,
                        )
                        await mw(msg)

                        msg = self.gen_hdr_stop(
                            name=str(path),
                            mode="restart" if save_state else "next",
                        )
                        self.write_monitor(msg)
                        task_status.started(scope)

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
                            await mw.flush()
            finally:
                self._writing.remove(str(path))
                self._writing_done.set()

    @staticmethod
    async def _save_stream(rdr, mw, shorter, ign):
        # helper for .save_stream() to keep the indent levels down

        last_saved = time.monotonic()
        last_saved_count = 0
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
                d, p = shorter.short(path)
                await mw([d, p, data, *meta.dump()])
                last_saved_count += 1
            elif isinstance(msg, Tag) and msg.tag == CBOR_TAG_MOAT_FILE_END:
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
        while True:
            now = datetime.now(UTC)
            fn = dest / now.strftime(save.name)
            await fn.parent.mkdir(exist_ok=True, parents=True)
            await self.run_saver(path=fn)
            if task_status is not None:
                task_status.started()
                task_status = None
            await anyio.sleep(save.interval)

        task_status.started()

    async def run_saver(self, path: PathType|None, save_state: bool = True):
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
                ),
            )
        else:
            self.write_monitor(self.gen_hdr_stop(reason="log_end"))

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
            await _tg.start(self._read_stamp)

            # retrieve data

            await _tg.start(self._read_initial)

            # save data

            sd = anyio.Path(self.cfg.server.save.dir)
            if await sd.is_dir():
                await _tg.start(self._save_task)

            # let clients in
            # TODO config via database

            ports = []
            if "ports" in self.cfg.server:
                for name, conn in self.cfg.server.ports.items():
                    ports.append(await listen_tg.start(self._run_server, client_tg, f"{self.name}-{name}", conn))
            if not ports:
                conn = attrdict(host="localhost",port=self.cfg.server.port)
                ports.append(await listen_tg.start(self._run_server, client_tg, f"{self.name}-default", conn))

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

            task_status.started((self, ports))
            self.logger.info("Startup done")

            # maintainance

            await _tg.start(self._flush_deleted)

            # wait for some stop signal

            await self._stop_flag.wait()

            # announce that we're going down

            # TODO listen to this message and possibly take over
            await self.backend.send(
                topic=P(":R.run.service.down.main"),
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
            _tg.cancel_scope.cancel()  # pyright:ignore  # ??

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

    async def _read_stamp(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Task to read the main service monitoring channel
        """
        async with self.backend.monitor(P(":R.run.service.main.stamp")) as mon:
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
                async with BasicLink(self.cfg, name, data) as conn:
                    await self._sync_one(conn)
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
                meta = MsgMeta._moat__restore(mt, NotGiven)  # noqa:SLF001
                meta.source = "_Load"
                if self.maybe_update(prefix + path, data, meta):
                    upd += 1
                else:
                    skp += 1
                self.logger.debug("Sync Msg %r", msg)
        self.logger.info("Sync finished. %d new, %d existing", upd, skp)

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

            async with anyio.create_task_group() as tgx:
                tgx.start_soon(self._get_remote_data, main, ready)
                tgx.start_soon(self._read_saved_data, ready)

            if not ready.is_set():
                raise RuntimeError("NO DATA")

    async def _read_saved_data(self, ready: anyio.Event):
        save = self.cfg.server.save
        dest = anyio.Path(save.dir)
        if not await dest.is_dir():
            self.logger.info("No saved data in %r", str(dest))
            return

        fs = []
        async for p, _d, f in dest.walk():
            for ff in f:
                fs.append(p / ff)
        fs.sort()

        tupd = 0
        while fs:
            fn = fs.pop()
            if str(fn) in self._writing:
                continue
            async with MsgReader(fn, codec="std-cbor") as rdr:
                hdr = await anext(rdr)
                if isinstance(hdr, Tag) and hdr.tag == CBOR_TAG_CBOR_LEADER:
                    hdr = hdr.value
                if not isinstance(hdr, Tag) or hdr.tag != CBOR_TAG_MOAT_FILE_ID:
                    raise ValueError(f"First entry is {hdr!r}")

                pl = PathLongener()
                upd, skp = 0, 0
                ehdr = None
                async for msg in rdr:
                    if isinstance(msg, Tag):
                        if msg.tag == CBOR_TAG_MOAT_FILE_ID:
                            # concatenated files?
                            if ehdr is None:
                                raise ValueError("START within file %r", str(fn))
                            # TODO verify that these belong together
                            ehdr = None

                        elif msg.tag == CBOR_TAG_MOAT_FILE_END:
                            if ehdr is not None:
                                raise ValueError("Duplicate END in %r", str(fn))
                            ehdr = msg
                            break
                        continue
                    d, p, data, *mt = msg
                    path = pl.long(d, p)
                    meta = MsgMeta._moat__restore(mt, NotGiven)  # noqa:SLF001
                    meta.source = "_file"
                    if self.maybe_update(path, data, meta):
                        # Entries that have been deleted don't count as updates
                        if data is not NotGiven:
                            upd += 1
                    else:
                        skp += 1

                self.logger.info("Restore %r: %d/%d", str(fn), upd, skp)
                tupd += upd
                if not upd and ehdr is not None and "error" not in ehdr.value:
                    break

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
            seen[msg.meta.origin] = sn + 1

        pass

    def get_cached_error(self, name) -> Exception|str|None:
        return self._error_cache.pop(name, None)

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

        The actual work happens in `ServerClient.run`. This wrapper
        mainly tries to record what went wrong on the server so the next
        client session can ask.

        TODO, for the most part. The stream is
        """
        c = None
        cnr = -1
        try:
            c = ServerClient(server=self, name=name, stream=stream)
            cnr = c.client_nr
            try:
                self._clients.add(c)
                await c.run()
            finally:
                self._clients.remove(c)
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
                    self.logger.exception("Client connection killed", exc_info=exc)
            if exc is None:
                exc = "Cancelled"
            self._error_cache[name] = cast(Exception,exc)
            self.logger.debug("XX END XX %d", cnr)

        finally:
            with anyio.move_on_after(2, shield=True):
                await stream.aclose()
