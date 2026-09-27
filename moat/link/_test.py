from __future__ import annotations

import anyio
import os
import sys
import time
from contextlib import asynccontextmanager, nullcontext
from functools import partial
from pathlib import Path as FSPath
from tempfile import TemporaryDirectory

from moat.util import (
    # pylint:disable=no-name-in-module,
    CtxObj,
    NotGiven,
    ValueEvent,
    attrdict,
    combine_dict,
    merge,
)
from moat.lib.config import CFG
from moat.lib.path import P, Root
from moat.link.backend import get_backend
from moat.link.client import Link
from moat.link.server import Server

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import Path
    from moat.link.backend import Backend
    from moat.link.client import LinkCommon, LinkSender

    from collections.abc import AsyncIterator
    from typing import Literal, Never, Self


otm = time.time

_seq = 0


# TODO launch a "real" broker instead


async def run_broker(cfg, *, task_status):
    """
    Runs a basic MQTT broker.

    The task status returns the port we're listening on.
    """
    cfg  # pyright:ignore # noqa:B018

    if False:
        # Just use the system MQTT broker.
        # TODO: This requires cleaning up retained messages.
        task_status.started(1883)
        return

    elif False:
        # Use the experimental moat.lib.mqtt broker.
        from moat.lib.mqtt import AsyncMQTTBroker  # noqa:PLC0415

        broker = AsyncMQTTBroker(("127.0.0.1", 0))
        await broker.serve(task_status=task_status)

    else:
        # Use a standalone instance of FlashMQ.
        async with (
            anyio.TemporaryDirectory() as td,
            anyio.create_task_group() as tg,
        ):
            sock_path = str(anyio.Path(td) / "flashmq.sock")
            tf = anyio.Path(td) / "config"
            await tf.write_text(
                f"""\
allow_anonymous true
retained_messages_mode enabled_without_persistence
thread_count 1

log_level info
log_subscriptions true

listen {{
    protocol mqtt
    inet_protocol unix
    unix_socket_path {sock_path}
}}
"""
            )

            tg.start_soon(
                partial(
                    anyio.run_process,
                    ["flashmq", "-c", str(tf)],
                    stderr=sys.stderr,
                    stdout=sys.stdout,
                    env={**os.environ, "HOME": td},
                )
            )
            for _ in range(20):
                try:
                    sock = await anyio.connect_unix(sock_path)
                except OSError:
                    await anyio.sleep(0.1)
                else:
                    await sock.aclose()
                    break
            else:
                raise RuntimeError("Could not connect to FlashMQ")

            task_status.started(sock_path)


class Scaffold(CtxObj):
    """
    Basic testcase runner for testing with an ephemeral MQTT server.

    If @cfg is `True`, place our mod in (and use) the global `moat.link`
    subconfig. Otherwise, pass in the `moat` subconfig.
    """

    tempdir: FSPath | None

    def __init__(
        self, cfg: attrdict | Literal[True], use_servers=True, tempdir: str | None = None
    ):
        cf = attrdict(
            root=P("test.moat.link"),
            backend=attrdict(
                driver="mqtt",
                codec="std-cbor",
                keep_alive=9999,
            ),
            server=attrdict(
                ping=attrdict(
                    cycle=0.5,
                    gap=0.15,
                    override=True,
                ),
                timeout=attrdict(startup=3),
            ),
        )
        # `Link.__init__` reads the *global* ``CFG.moat.link.root``,
        # so we always need to override the placeholder there too.
        if CFG.result.moat.link.root == P("XXX.NotConfigured.YZ"):
            CFG.mod(P("moat.link.root"), cf.root)
        if cfg is True:
            CFG.mod(P("moat.link"), cf)
            self.cfg = CFG.result.moat.link
        else:
            self.cfg = cfg.link
            if self.cfg.get("root", None) == P("XXX.NotConfigured.YZ"):
                self.cfg.root = cf.root
            merge(self.cfg, cf)
        self._tempdir = tempdir

        if not use_servers:
            self.cfg.client.init_timeout = None

    @asynccontextmanager
    async def _ctx(self) -> AsyncIterator[Self]:
        Root.set(self.cfg.root)

        with (
            nullcontext(
                self._tempdir,
            )
            if self._tempdir is not None
            else TemporaryDirectory() as tempdir
        ):
            assert tempdir is not None
            self.tempdir = FSPath(tempdir)
            async with (
                anyio.create_task_group() as tg,
                anyio.create_task_group() as self.tg,
            ):
                bsock = await tg.start(run_broker, self.cfg)
                self.cfg.backend.transport = "unix"
                self.cfg.backend.port = bsock
                try:
                    yield self
                finally:
                    with anyio.CancelScope(shield=True):
                        await anyio.sleep(0.1)
                        self.tg.cancel_scope.cancel()  # pyright:ignore
                        await anyio.sleep(0.1)
                        tg.cancel_scope.cancel()  # pyright:ignore
                        await anyio.sleep(0.1)

    async def backend(self, cfg: dict | None = None, **kw):
        """
        Start a backend (background task)
        """
        return await self.tg.start(self._run_backend, cfg, kw)

    @asynccontextmanager
    async def backend_(self, cfg: dict | None, **kw) -> AsyncIterator[Backend]:
        """
        Start a backend (async context manager).
        """
        cfg = combine_dict(cfg, self.cfg, cls=attrdict) if cfg else self.cfg
        async with get_backend(cfg, **kw) as bk:
            yield bk

    async def _run_backend(self, cfg: dict | None, kw: dict, *, task_status) -> Backend:
        """
        Start a backend (Helper).
        """
        async with self.backend_(cfg, **kw) as bk:
            task_status.started(bk)
            await anyio.sleep_forever()
            raise AssertionError

    async def server(self, cfg: dict | None = None, **kw) -> tuple[Server, list[dict]]:
        """
        Start a server (background task)

        Returns the server object and the ports it runs on.
        """
        return await self.tg.start(self._run_server, cfg, kw)

    async def _run_server(self, cfg, kw, *, task_status) -> None:
        """
        Run a basic MoaT-Link server. (Helper task)
        """
        cfg = combine_dict(cfg, self.cfg, cls=attrdict) if cfg else self.cfg
        if "ports" in cfg["server"]:
            cfg["server"]["ports"]["main"]["port"] = 0
        cfg["server"]["port"] = 0
        if self.tempdir is not None:
            cfg["server"]["save"]["dir"] = self.tempdir / "data"

        name = kw.pop("name", None)
        if name is None:
            global _seq
            _seq += 1
            name = f"S_{_seq}"

        s = Server(cfg, name, **kw)
        # run the server in this task's scope, so that leaving `server_`
        # really stops it
        async with anyio.create_task_group() as tg:
            await tg.start(s.serve)
            task_status.started(s)
            await anyio.sleep_forever()

    @asynccontextmanager
    async def server_(self, cfg: dict | None = None, **kw) -> AsyncIterator[Server]:
        """
        Runs a basic MoaT-Link server. (async context manager)
        """
        async with anyio.create_task_group() as tg:
            yield await tg.start(self._run_server, cfg, kw)
            tg.cancel_scope.cancel()

    async def client(self, *a, **kw):
        """
        Start a client (background task)
        """
        cl = await self.tg.start(partial(self._run_client, *a, **kw))
        return cl

    async def _run_client(self, *a, task_status, **kw) -> Never:
        async with self.client_(*a, **kw) as cl:
            task_status.started(cl)
            await anyio.sleep_forever()
        raise AssertionError("unreachable")

    @asynccontextmanager
    async def client_(
        self, cfg: dict | None = None, cli: LinkCommon | None = None, name=None
    ) -> AsyncIterator[LinkSender]:
        """
        Start a client (async context manager)
        """
        if cli is None:
            cfg = combine_dict(cfg, self.cfg, cls=attrdict) if cfg else self.cfg

            global _seq
            _seq += 1
            name = f"C_{_seq}"

            cli = Link(cfg, name)

        async with cli as li:
            yield li  # ty:ignore[invalid-yield] ## XXX TODO

    async def run(self, *args, do_stdout: bool = True):
        """Invoke a ``moat`` CLI command against this scaffold's broker.

        Mirrors :py:meth:`moat.kv.mock.S.run`.  The scaffold's broker
        port plus the few other settings the link client needs are
        injected via top-level ``-s`` options so the freshly-loaded
        configuration inside :func:`moat.src.test.run` sees them.

        Args:
            *args: command-line arguments (a single string is shell-split).
            do_stdout: capture stdout into the returned result.
        """
        from moat.src.test import run as run_  # noqa:PLC0415

        if len(args) == 1:
            a0 = args[0]
            if isinstance(a0, str):
                args = tuple(a0.split(" "))
            else:
                args = tuple(a0)
        bcfg = self.cfg.backend
        pre: list[str] = [
            "-s",
            "moat.link.backend.driver",
            str(bcfg.get("driver", "mqtt")),
            "-s",
            "moat.link.backend.codec",
            str(bcfg.get("codec", "std-cbor")),
        ]
        transport = bcfg.get("transport", "tcp")
        pre.extend(("-s", "moat.link.backend.transport", str(transport)))
        if transport == "unix":
            pre.extend(("-s", "moat.link.backend.port", str(bcfg.port)))
        else:
            pre.extend((
                "-s",
                "moat.link.backend.host",
                str(bcfg.get("host", "127.0.0.1")),
                "-s",
                "moat.link.backend.port",
                f"={int(bcfg.port)}",
            ))
        pre.extend(("-s", "moat.link.root", f".{self.cfg.root}"))
        return await run_(*pre, *args, do_stdout=do_stdout)

    @asynccontextmanager
    async def do_watch(
        self, path: Path, exp=NotGiven, n: int = 0, **kw
    ) -> AsyncIterator[ValueEvent]:
        """
        Run a client that expects ``exp`` and appends all non-exp
        results to ``rd``.

        All other args+kw are forwarded to `Link.d_watch`.

        The results are appended to a list that's posted to the event when
        `do_watch` ends (for whatever reason).

        Args:
            path: The Link path to watch.
            exp: Expected element, or `NotGiven`.
            n: Exit after ``n`` messages. Default: Don't.
        """
        async with self.client_() as c, anyio.create_task_group() as tg:
            evt = ValueEvent()

            @tg.start_soon
            async def work():
                res = []
                try:
                    async with c.d_watch(path, **kw) as mon:
                        async for r in mon:
                            if kw.get("meta"):
                                t = time.time()
                                assert t - 1 < r[-1].timestamp < t
                            elif not kw.get("subtree"):
                                # neither meta nor subtree
                                r = (r,)  # noqa:PLW2901
                            if (
                                exp is not NotGiven
                                and (not kw.get("subtree") or not len(r[0]))
                                and r[kw.get("subtree", 0)] == exp
                            ):
                                # Skip if toplevel match
                                return
                            res.append(r)
                            if len(res) == n:
                                return
                finally:
                    evt.set(res)

            yield evt
            tg.cancel_scope.cancel()
