#!/usr/bin/python3

#
# This is tne multiplexer, which affords a socket so that clients may
# connect to the embedded system to get their commands forwarded.

import importlib
import logging
import os
import sys
from concurrent.futures import CancelledError
from contextlib import asynccontextmanager, contextmanager
from pprint import pformat

import anyio
from moat.util import attrdict, merge, to_attrdict

from ..app import ConfigError
from ..cmd import BaseCmd
from ..compat import Event, TaskGroup
from ..main import Request, ClientBaseCmd
from ..stacks.unix import unix_stack_iter
from .stack import RemoteError, SilentRemoteError

# from distmqtt.client import open_mqttclient


logger = logging.getLogger(__name__)

class CommandClient(Request):
    """
    This Request stub connects a stream to a multiplexer.
    """

    def __init__(self, parent, mplex=None, cfg=None):
        super().__init__(parent)
        self.stack(ClientBaseCmd, cfg=cfg)
        self.mplex = mplex

    async def _read_task(self):
        while True:
            msg = await self.parent.recv()
            await self.dispatch(msg)

    async def run(self):
        async with TaskGroup() as tg:
            self.__tg = tg
            await tg.spawn(self._read_task, _name="mp_rep_read")
            try:
                await self.mplex.running.wait()
                await self.send_nr("link", True)
                await self.mplex.stopped.wait()

            finally:
                for k, e in self.reply.items():
                    if isinstance(e, Event):
                        self.reply[k] = CancelledError()
                        e.set()
                with anyio.move_on_after(2, shield=True):
                    await self.send_nr("link", False)
                tg.cancel()

    async def dispatch(self, msg):
        if not isinstance(msg, dict):
            logger.warning("?1 %s", msg)
            return

        if 'a' not in msg:
            # A reply. However, nobody sends requests to command clients.
            logger.warning("?2 %s", msg)
            return

        await self.__tg.spawn(self._handle_request, msg, _name="mp_req_" + repr(msg["a"]))

    async def _handle_request(self, msg):
        a = msg.pop("a")
        i = msg.pop("i", None)
        d = msg.pop("d", None)

        try:
            res = await self.mplex.send(a, d)
        except Exception as exc:
            if isinstance(exc, SilentRemoteError) or (
                isinstance(exc, RemoteError) and exc.args and len(exc.args[0]) < 3
            ):
                pass
            else:
                logger.exception("handling %s %s %s %s", a, i, d, msg)
            if i is None:
                return
            res = {'e': exc.args[0] if isinstance(exc, RemoteError) else repr(exc), 'i': i}
        else:
            if i is None:
                return
            res = {'d': res, 'i': i}
        await self.parent.send(res)


#
# We need a somewhat-reliable link, with assorted link state.
#


class MultiplexCommand(BaseCmd):
    """
    Server-side main command handler.
    """
    # main command handler
    def __init__(self, parent, *, cfg):
        super().__init__(parent)

        self.cfg = cfg
        self.dis_mplex = _MplexCommand(self)
        self.dis_local = _LocalCommand(self)

    def cmd_link(self, s):
        self.request._process_link(s)

    async def start_sub(self, tg):
        pass  # we do that ourselves


class _MplexCommand(BaseCmd):
    """
    "mplex" child command handler.

    ["mplex","boot"] calls the "cmd_boot" method of the multiplexer.
    """

    async def cmd_boot(self):
        e = self.request.stopped
        await self.send(["sys", "boot"], code="SysBooT")
        await e.wait()
        await self.request.run_flag.wait()

    async def cmd_cfg(self):
        r = self.request
        cfg = to_attrdict(await r.get_cfg())
        self.base.cfg = merge(self.base.cfg, cfg, drop=True)
        await r.update_config()


class _LocalCommand(BaseCmd):
    """
    "local" child command handler.

    ["local","foo","bar"] calls the "loc_bar" method of the "foo" module.
    """
    async def dispatch(self, action, msg):
        if not isinstance(action, (tuple, list)) or len(action) <= 1:
            raise RuntimeError("local/* calls require the path to be a list")
        p = self.parent
        for a in action[:-1]:
            p = getattr(p, "dis_" + a)
        p = getattr(p, "loc_" + action[-1])

        if isinstance(msg, dict):
            r = p(**msg)
        else:
            r = p(msg)
        if hasattr(r, "throw"):  # iscoroutine
            r = await r
        return r


class _StatCommand(BaseCmd):
    async def cmd_stat(self):
        pass


class Command(BaseCmd):
    pass


class Multiplexer(Request):
    """
    This is the server-side multiplexer object. It connects to the embedded
    system via a TCP socket. It offers a Unix socket for client programs,
    including FUSE mounts.

    Unix socket paths are relative to XDG_RUNTIME_DIR if they don't start
    with a slash.
    """
    APP="moat.micro.app"

    sock = None
    _cancel = None
    _tg = None

    def __init__(self, stream_factory, socket, *, cfg=None, load_cfg=True):
        """
        Set up a multiplexer to a MicroPython client.

        "StreamFactory" must be an async context manager that installs its
        argument as the Request handler.

        If @load_cfg is set (the default), any configuration is read from the client.
        """
        super().__init__(None)
        self.stack(MultiplexCommand, cfg=cfg)
        self.stream_factory = stream_factory
        self.socket = socket
        self.load_cfg = load_cfg

        # self.mqtt_cfg = mqtt
        # self.mqtt_sub = {}

        self.next_mid = 0
        self.next_stream = 0
        self.next_sub = 0
        self.subs = {}  # nr > topic,codec,cs
        self.apps = {}  # name > app

        # wait on some of these to sync with the link state
        self.stopped = anyio.Event()
        self.running = anyio.Event()
        self.serving = anyio.Event()

        # use this to coordinate client shutdown
        self.run_flag = anyio.Event()

    def _process_link(self, s):
        if s:
            logger.info("Client: Up")
            self.running.set()
        else:
            logger.info("Client: Down")
            self.stopped.set()

    def _gen_req(self, parent, ready=None, cfg=None):
        self.parent = parent
        # "ready" is only used on the client side
        return self

    async def update_config(self):
        await self._setup_apps()

    async def serve(self):
        async with self.stream_factory(self._gen_req):
            await self.running.wait()
            await self._serve_stream(self.socket)

    async def wait(self):
        await self.serving.wait()
        await self.running.wait()

    async def send(self, action, msg=None, **kw):
        if action[0] in {"mplex", "local"}:
            if msg is None:
                msg = kw
            return await self.child.dispatch(action, msg)
        else:
            return await super().send(action, msg, **kw)

    async def run_sub(self):
        pass

    async def _setup_cfg(self, tg):
        if self.load_cfg:
            logger.debug("Retrieving config")
            with anyio.fail_after(10):
                self.cfg = await self.get_cfg()
            self.cfg = to_attrdict(self.cfg)
            logger.debug("Config:\n%s", pformat(self.cfg))
        else:
            logger.debug("Sending config")
            await self.set_cfg(self.cfg)

    async def run(self):
        """
        This run method controls a single invocation of the link.
        """
        logger.debug("Connected, starting up")
        async with TaskGroup() as tg:
            # self.tg1 = tg
            self.__tg = tg
            try:
                self._cancel = tg.cancel_scope
                await tg.spawn(super().run)
                await self._setup_cfg(tg)
                await self._setup_apps()
                self.running.set()
                await self.send_nr(["sys", "is_up"])
                await self.stopped.wait()  # triggered by link-down message
            finally:
                self.parent = None
                self.stopped.set()
                tg.cancel()

    async def _serve_stream(self, path, *, task_status=None):
        logger.info("Listen for commands on %r", self.socket)
        async for t, b in unix_stack_iter(
            self.socket, evt=self.serving, log="Client", request_factory=CommandClient, cfg=self.cfg
        ):
            t.mplex = self
            await self.__tg.spawn(self._run_client, b, _name="mp_client")

    async def _run_client(self, b):
        try:
            return await b.run()
        except (EOFError, anyio.EndOfStream):
            pass
        except anyio.BrokenResourceError:
            pass
        except Exception as exc:
            logger.exception("ERROR on Client Conn %s: %r", b, exc)

    @contextmanager
    def _attached(self, stream):
        self.next_stream += 1
        sid = self.next_stream

        stream._mplex_sid = sid
        self.streams[sid] = stream
        try:
            yield stream
        finally:
            del self.streams[sid]

    async def _handle_stream(self, sock):
        stream = Stream(self, sock)
        with self._attached(stream):
            try:
                await stream.run()
            except anyio.EndOfStream:
                pass
            except Exception as e:
                logger.exception("Stream Crash")
                try:
                    await stream.send(a='e', d=repr(e))
                except Exception:
                    pass

    async def submit(self, serv, msg, seq):
        self.next_mid += 1
        mid = self.next_mid
        self.mseq[mid] = (serv._mplex_sid, seq)
        await self.send(i=mid, **msg)
