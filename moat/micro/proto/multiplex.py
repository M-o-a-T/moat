#!/usr/bin/python3

#
# This is tne multiplexer, which affords a socket so that clients may
# connect to the embedded system to get their commands forwarded.

import logging
import os
import sys
from concurrent.futures import CancelledError
from contextlib import asynccontextmanager, contextmanager

import anyio
#from distmqtt.client import open_mqttclient

from . import RemoteError
from ..stacks.unix import unix_stack_iter
from ..compat import TaskGroup, Event, print_exc
from ..cmd import Request, BaseCmd

logger = logging.getLogger(__name__)


class IsHandled:
    pass


class CommandClient(Request):
    """
    This Request stub connects the multiplexer to a command client.
    """

    def __init__(self, parent, mplex=None):
        super().__init__(parent)
        self.mplex = mplex

    async def run(self):
        try:
            async with TaskGroup() as tg:
                self._tg = tg
                await tg.spawn(self._report_link)
                while True:
                    msg = await self.parent.recv()
                    await self.dispatch(msg)
        finally:
            for k,e in self.reply.items():
                if isinstance(e,Event):
                    self.reply[k] = CancelledError()
                    e.set()

    async def _report_link(self):
        while True:
            await self.mplex.running.wait()
            await self.send_nr("link",True)
            await self.mplex.stopped.wait()
            await self.send_nr("link",False)

    async def dispatch(self, msg):
        if not isinstance(msg,dict):
            print("?",msg)
            return

        if 'a' not in msg:
            # A reply. However, nobody sends requests to command clients.
            print("?",msg)
            return

        await self._tg.spawn(self._handle_request, msg)


    async def _handle_request(self, msg):
        a = msg.pop("a")
        i = msg.pop("i", None)
        d = msg.pop("d", None)

        try:
            res = await self.mplex.client_cmd(a,d)
        except Exception as exc:
            print("ERROR handling",a,i,d,msg, file=sys.stderr)
            print_exc(exc)
            if i is None:
                return
            res = {'e':exc.args[0] if isinstance(exc,RemoteError) else repr(exc),'i':i}
        else:
            if i is None:
                return
            res = {'d':res,'i':i}
        await self.parent.send(res)


class MultiplexCommand(BaseCmd):
    async def cmd_boot(self):
        await self.send(["sys","boot"], code="SysBooT")

class Multiplexer(Request):
    """
    This is the multiplexer object. It connects to the embedded system via
    a TCP socket. It offers a Unix socket for client programs, including
    FUSE mounts.

    Unix socket paths are relative to XDG_RUNTIME_DIR if they don't contain a
    slash.
    """

    sock = None
    _cancel = None
    _tg = None

    def __init__(self, stream_factory, socket, watchdog=0):
        """
        Set up a MicroPython multiplexer.

        "StreamFactory" must be an async context manager that installs its
        argument as the Request handler.
        """
        super().__init__(None)
        self.stream_factory = stream_factory
        self.socket = socket

        #self.mqtt_cfg = mqtt
        #self.mqtt_sub = {}
        self.watchdog = watchdog

        self.next_mid = 0
        self.next_stream = 0
        self.next_sub = 0
        self.subs = {}  # nr > topic,codec,cs

        # wait on this to sync with the link state
        self.running = anyio.Event()
        self.stopped = anyio.Event()
        self.stopped.set()

        # use this to stop/restart the link
        self.do_stop = anyio.Event()
        self.quitting = False
        self.last_exc = None

        self.stack(MultiplexCommand)

    def _gen_req(self, parent):
        self.parent = parent
        return self

    async def _run_stack(self):
        """Run (and re-run) a multiplexed link."""
        backoff = 1
        while not self.quitting:
            try:
                if self.stopped.is_set():
                    self.stopped = Event()
                logger.info("Starting up")

                try:
                    async with self.stream_factory(self._gen_req):
                        logger.info("Startup done")
                        await anyio.sleep(1)
                        logger.info("Running OK")
                        self.running.set()
                        await anyio.sleep(60)
                        backoff = 1
                        await self.do_stop.wait()
                        await self._cancel()
                finally:
                    self.parent = None
                    if self.running.is_set():
                        self.running = Event()
                    if self.do_stop.is_set():
                        self.do_stop = Event()
                    self.stopped.set()

            except Exception as exc:
                self.last_exc = exc
                print_exc(exc)

                await anyio.sleep(backoff)
                if backoff<20:
                    backoff *= 1.4

            except BaseException as exc:
                self.last_exc = type(exc)
                raise

            else:
                if not self.quitting:
                    await anyio.sleep(1)


    async def serve(self):
        async with TaskGroup() as tg:
            self.tg = tg
            await tg.spawn(self._run_stack)
            await self.running.wait()
            await self._serve_stream(self.socket)


#   @asynccontextmanager
#   async def _mqtt(self):
#       if self.mqtt_cfg is None:
#           yield self
#           return
#       async with open_mqttclient(config=dict(uri=self.mqtt_cfg)) as mqtt:
#           try:
#               self.mqtt = mqtt
#               yield self
#           finally:
#               self.mqtt = None

#   async def subscribed_mqtt(self, topic, raw=False, nr=None, *, task_status):
#       """Forward this topic to the embedded system.

#       This is a subtask.
#       """
#       if self.mqtt is None:
#           return
#       if isinstance(topic, str):
#           topic = topic.split("/")
#       spl = '#' in topic or '+' in topic
#       codec = None if raw else "msgpack"
#       async with self.mqtt.subscription(topic, codec=codec) as sub:
#           if nr is None:
#               self.next_sub += 2
#               nr = self.next_sub
#               await self.send(a="ms", p=nr, d=topic)
#           task_status.started(nr)
#           try:
#               with anyio.CancelScope() as cs:
#                   self.subs[nr] = (topic, codec, cs)
#                   async for msg in sub:
#                       try:
#                           if spl:
#                               # wildcard resolution
#                               w = []
#                               rt = msg.topic.split("/")
#                               for k in topic:
#                                   if k == "+":
#                                       w.append(rt[0])
#                                   elif k == "#":
#                                       w.extend(rt)
#                                       break
#                                   elif k != rt[0]:
#                                       logger.warning(
#                                           "Strange topic: %r vs %r", msg.topic, "/".join(topic)
#                                       )
#                                       continue
#                                   rt = rt[1:]
#                               await self.send(a="m", p=nr, d=msg.data, w=w)
#                           else:
#                               await self.send(a="m", p=nr, d=msg.data)
#                       except Exception as exc:
#                           logger.exception("Received from %r: %r", msg, exc)

#           except Exception as exc:
#               logger.exception("SubscribeLoop: %r", exc)
#               await self.send(a="mu", p=nr)
#           finally:
#               try:
#                   del self.subs[nr]
#               except KeyError:
#                   pass

    async def client_cmd(self, a,d):
        if a[0] == "mplex":
            return await self.child.dispatch(a[1:],d)
        else:
            return await self.send(a,d)

    async def run(self):
        """
        This run method controls a single invocation of the link.
        """
        async with anyio.create_task_group() as tg:
            # self.tg1 = tg
            self._cancel = tg.cancel_scope

            if self.watchdog:
                await tg.spawn(self._watchdog)
                print(f"Watchdog: {self.watchdog} seconds")
            await super().run()

    async def _watchdog(self):
        await self.running.wait()
        await self.send(["sys","wdg"], d=self.watchdog * 2.2)
        while True:
            await anyio.sleep(self.watchdog)
            with anyio.fail_after(2):
                await self.send(["sys","wdg"], p=True)

    async def _serve_stream(self, path, *, task_status=None):
        logger.info("Listen for commands on %r", self.socket)
        async for t,b in unix_stack_iter(self.socket, log="Client", request_factory=CommandClient):
            t.mplex = self
            await self._tg.spawn(self._run_client, b)

    async def _run_client(self, b):
        try:
            return await b.run()
        except anyio.EndOfStream:
            pass
        except anyio.BrokenResourceError:
            pass
        except Exception as exc:
            print("ERROR on Client Conn", b)
            print_exc(exc)

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
