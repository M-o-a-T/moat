
try:
    from contextlib import asynccontextmanager, AsyncExitStack
except ImportError:
    from async_generator import asynccontextmanager
    from async_exit_stack import AsyncExitStack
import trio
import mock
import attr
import copy
import trio
import time
from pprint import pformat
from functools import partial
try:
    from concurrent.futures import CancelledError
except ImportError:
    class CancelledError(Exception):
        pass

from distkv.client import open_client
from distkv.default import CFG
from distkv.server import Server
from distkv.codec import unpacker
from distkv.util import attrdict, Queue

import logging
logger = logging.getLogger(__name__)

otm = time.time

@asynccontextmanager
async def stdtest(n=1, run=True, client=True, ssl=False, tocks=20, **kw):
    TESTCFG = copy.deepcopy(CFG)
    TESTCFG.server.port = None
    TESTCFG.root="test"

    if ssl:
        import ssl
        import trustme
        ca = trustme.CA()
        cert = ca.issue_server_cert(u"test.distkv.m-o-a-t.org")
        server_ctx = ssl.create_default_context(purpose=ssl.Purpose.CLIENT_AUTH)
        client_ctx = ssl.create_default_context(purpose=ssl.Purpose.SERVER_AUTH)
        ca.configure_trust(client_ctx)
        cert.configure_cert(server_ctx)
    else:
        server_ctx = client_ctx = None

    clock = trio.hazmat.current_clock()
    clock.autojump_threshold = 0.01

    @attr.s
    class S:
        tg = attr.ib()
        serfs = attr.ib(factory=set)
        splits = attr.ib(factory=set)
        s = [] # servers
        c = [] # clients

        async def ready(self, i=None):
            if i is not None:
                await self.s[i].is_ready
                return self.s[i]
            for s in self.s:
                if s is not None:
                    await s.is_ready
            return self.s

        def __iter__(self):
            return iter(self.s)

        @asynccontextmanager
        async def client(self, i:int = 0, **kv):
            """Get a client for the i'th server."""
            await self.s[i].is_serving
            host,port = st.s[i].ports[0][0:2]
            async with open_client(host=host, port=port, ssl=client_ctx, **kv) as c:
                yield c

        def split(self, s):
            assert s not in self.splits
            logger.debug("Split: add %d",s)
            self.splits.add(s)

        def join(self, s):
            logger.debug("Split: join %d",s)
            self.splits.remove(s)

    async def mock_send_ping(self,old):
        assert self._tock < tocks, "Test didn't terminate. Limit:"+str(tocks)
        await old()

    async def mock_get_host_port(st, node):
        i = int(node.name[node.name.rindex('_')+1:])
        s = st.s[i]
        await s.is_serving
        return s.ports[0][0:2]

    def tm():
        try:
            return trio.current_time()
        except RuntimeError:
            return otm()

    async with trio.open_nursery() as tg:
        st = S(tg)
        async with AsyncExitStack() as ex:
            ex.enter_context(mock.patch("time.time", new=tm))
            ex.enter_context(mock.patch("asyncserf.serf_client", new=partial(mock_serf_client,st)))

            for i in range(n):
                name = "test_"+str(i)
                args = kw.get(name, kw.get('args', attrdict()))
                if 'cfg' not in args:
                    args['cfg'] = args.get('cfg',TESTCFG).copy()
                    args['cfg']['serf'] = args['cfg']['serf'].copy()
                    args['cfg']['serf']['i'] = i
                    if server_ctx:
                        args['cfg']['server'] = args['cfg']['server'].copy()
                        args['cfg']['server']['ssl'] = server_ctx
                s = Server(name, **args)
                ex.enter_context(mock.patch.object(s, "_send_ping", new=partial(mock_send_ping,s,s._send_ping)))
                ex.enter_context(mock.patch.object(s, "_get_host_port", new=partial(mock_get_host_port,st)))
                st.s.append(s)

            class IsStarted:
                def __init__(self,n):
                    self.n = n
                    self.dly = trio.Event()
                def started(self, x=None):
                    self.n -= 1
                    if not self.n:
                        self.dly.set()
            is_started = IsStarted(n)
            for i in range(n):
                if kw.get("run_"+str(i), run):
                    r = trio.Event()
                    tg.start_soon(partial(st.s[i].serve, task_status=is_started))
                else:
                    is_started.started() # mock me
            await is_started.dly.wait()
            try:
                yield st
            finally:
                logger.info("Runtime: %s", clock.current_time())
                tg.cancel_scope.cancel()
        logger.info("End")
        pass # unwinding ex:AsyncExitStack

@asynccontextmanager
async def mock_serf_client(master, **cfg):
    async with trio.open_nursery() as tg:
        ms = MockServ(tg, master, **cfg)
        master.serfs.add(ms)
        try:
            yield ms
        finally:
            master.serfs.remove(ms)
        pass # terminating mock_serf_client nursery

class MockServ:
    def __init__(self, tg, master, **cfg):
        self.cfg = cfg
        self.tg = tg
        self.streams = {}
        self._master = master

    def __hash__(self):
        return id(self)

    async def spawn(self, fn, *args, **kw):
        async def run():
            try:
                await fn(*args, **kw)
            except CancelledError:
                pass
        return self.tg.start_soon(run)

    def stream(self, event_types='*'):
        if ',' in event_types or not event_types.startswith('user:'):
            raise RuntimeError("not supported")
        s = MockSerfStream(self, event_types)
        return s

    async def event(self, typ, payload, coalesce=False):
        try:
            logger.debug("SERF:%s: %r", typ, unpacker(payload))
        except Exception:
            logger.debug("SERF:%s: %r", typ, payload)

        for s in list(self._master.serfs):
            for x in self._master.splits:
                if (s.cfg.get('i',0) < x) != (self.cfg.get('i',0) < x):
                    break
            else:
                sl = s.streams.get(typ, None)
                if sl is not None:
                    for s in sl:
                        await s.q.put(payload)

class MockSerfStream:
    def __init__(self, serf, typ):
        self.serf = serf
        assert typ.startswith('user:')
        self.typ = typ[5:]

    async def __aenter__(self):
        logger.debug("SERF:MON START:%s", self.typ)
        self.q = Queue(100)
        self.serf.streams.setdefault(self.typ, []).append(self)
        return self

    async def __aexit__(self, *tb):
        self.serf.streams[self.typ].remove(self)
        logger.debug("SERF:MON END:%s", self.typ)
        del self.q

    def __aiter__(self):
        return self

    async def __anext__(self):
        res = await self.q.get()
        return attrdict(payload=res)

