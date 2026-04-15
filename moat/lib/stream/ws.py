"""
Websocket support for stream layers (CPython-specific).
"""

from __future__ import annotations

import anyio
from contextlib import suppress
from urllib.parse import urlsplit

import httpx
import wsproto
from wsproto.connection import ConnectionType
from wsproto.events import (
    AcceptConnection,
    BytesMessage,
    CloseConnection,
    Ping,
    RejectConnection,
    Request,
    TextMessage,
)

from moat.lib.micro import AC_use, Lock, log
from moat.lib.stream import BaseBlk

from typing import TYPE_CHECKING, cast  # isort:skip

if TYPE_CHECKING:
    from anyio.abc import ByteStream

    from httpx_ws import AsyncWebSocketSession

    from moat.util import attrdict
    from moat.lib.stream import BaseMsg
    from moat.lib.stream.base import Buffer, MutBuffer


class WsLink(BaseBlk):
    """
    A block stream that connects to a remote websocket server.
    """

    _crd_buf: bytearray

    def __init__(self, url: str, retry: dict | None = None, **kw):
        self.url = url
        if retry is None:
            retry = {}
        self.retry = retry
        self.kw = kw

    async def stream(self):  # noqa:D102
        from httpx_ws import (  # noqa:PLC0415
            WebSocketNetworkError,
            WebSocketUpgradeError,
            aconnect_ws,
        )

        retry = self.retry
        sl = retry.get("delay", 0.1)
        er: Exception | None = None
        n = 0
        deadline = anyio.current_time() + retry.get("timeout", 999)
        attempts = retry.get("attempts", 10)
        client = await AC_use(self, httpx.AsyncClient())
        try:
            while True:
                try:
                    ws = await AC_use(self, aconnect_ws(self.url, client=client, **self.kw))
                except (
                    OSError,
                    httpx.HTTPError,
                    WebSocketNetworkError,
                    WebSocketUpgradeError,
                ) as e:
                    er = e
                    if n > attempts or anyio.current_time() >= deadline:
                        raise TimeoutError from er
                    if n == 0:
                        log("Retrying: %s, %r", self.url, er)
                    n += 1
                    await anyio.sleep(sl)
                    sl *= retry.get("backoff", 1.3)
                else:
                    if n:
                        log("Success: %s", self.url)
                    return ws
        except TimeoutError:
            log("Fail: %s, %r", self.url, er)
            raise

    async def setup(self):  # noqa:D102
        await super().setup()

        self._crd_buf = bytearray()
        self._w_lock = Lock()

        self._b_send, self._b_recv = anyio.create_memory_object_stream[bytes](8)
        self._t_send, self._t_recv = anyio.create_memory_object_stream[bytes](8)
        await AC_use(self, self._b_send)
        await AC_use(self, self._b_recv)
        await AC_use(self, self._t_send)
        await AC_use(self, self._t_recv)

        self._tg = await AC_use(self, anyio.create_task_group())
        await AC_use(self, self._tg.cancel_scope.cancel)
        self._tg.start_soon(self._reader)

    async def _reader(self):
        from httpx_ws import WebSocketDisconnect, WebSocketNetworkError  # noqa:PLC0415

        ws = cast("AsyncWebSocketSession", self.s)
        bbuf = bytearray()
        tbuf = []
        try:
            while True:
                event = await ws.receive()
                if isinstance(event, BytesMessage):
                    if event.message_finished and not bbuf:
                        await self._b_send.send(bytes(event.data))
                    else:
                        bbuf.extend(event.data)
                        if event.message_finished:
                            await self._b_send.send(bytes(bbuf))
                            bbuf = bytearray()

                elif isinstance(event, TextMessage):
                    if event.message_finished and not tbuf:
                        await self._t_send.send(event.data.encode("latin-1"))
                    else:
                        tbuf.append(event.data)
                        if event.message_finished:
                            await self._t_send.send("".join(tbuf).encode("latin-1"))
                            tbuf = []

        except (EOFError, WebSocketDisconnect, WebSocketNetworkError):
            pass
        finally:
            with suppress(anyio.BrokenResourceError):
                await self._b_send.aclose()
            with suppress(anyio.BrokenResourceError):
                await self._t_send.aclose()

    async def snd(self, m: Buffer | bytes) -> None:  # noqa:D102
        from httpx_ws import WebSocketNetworkError  # noqa:PLC0415

        try:
            async with self._w_lock:
                await cast("AsyncWebSocketSession", self.s).send_bytes(bytes(m))
        except (OSError, WebSocketNetworkError) as exc:
            raise EOFError from exc

    async def rcv(self) -> Buffer | bytes:  # noqa:D102
        try:
            return await self._b_recv.receive()
        except (anyio.EndOfStream, anyio.ClosedResourceError) as exc:
            raise EOFError from exc

    async def cwr(self, buf: Buffer) -> None:
        "Send console bytes as one websocket text message."
        from httpx_ws import WebSocketNetworkError  # noqa:PLC0415

        try:
            async with self._w_lock:
                await cast("AsyncWebSocketSession", self.s).send_text(bytes(buf).decode("latin-1"))
        except (OSError, WebSocketNetworkError) as exc:
            raise EOFError from exc

    async def crd(self, buf: MutBuffer) -> int:
        "Read console bytes from queued websocket text messages."
        while not self._crd_buf:
            try:
                self._crd_buf.extend(await self._t_recv.receive())
            except (anyio.EndOfStream, anyio.ClosedResourceError) as exc:
                raise EOFError from exc
        n = min(len(buf), len(self._crd_buf))
        buf[:n] = self._crd_buf[:n]
        self._crd_buf = self._crd_buf[n:]
        return n


class SingleWsBlk(BaseBlk):
    """
    Adapt a single accepted TCP connection to a websocket block stream.
    """

    _crd_buf: bytearray
    _ws: wsproto.WSConnection | None
    path: str | None

    def __init__(self, stream: ByteStream, path: str | None = None):
        self._stream = stream
        self.path = path

    async def stream(self):  # noqa:D102
        return await AC_use(self, self._stream)

    async def setup(self):  # noqa:D102
        await super().setup()
        self._ws = wsproto.WSConnection(ConnectionType.SERVER)
        self._crd_buf = bytearray()
        self._w_lock = Lock()

        self._b_send, self._b_recv = anyio.create_memory_object_stream[bytes](8)
        self._t_send, self._t_recv = anyio.create_memory_object_stream[bytes](8)
        await AC_use(self, self._b_send)
        await AC_use(self, self._b_recv)
        await AC_use(self, self._t_send)
        await AC_use(self, self._t_recv)

        await self._handshake()

        self._tg = await AC_use(self, anyio.create_task_group())
        await AC_use(self, self._tg.cancel_scope.cancel)
        self._tg.start_soon(self._reader)

    async def _send_raw(self, data: bytes) -> None:
        try:
            await cast("ByteStream", self.s).send(data)
        except (anyio.EndOfStream, anyio.BrokenResourceError, anyio.ClosedResourceError) as exc:
            raise EOFError from exc

    async def _recv_raw(self, n: int = 65536) -> bytes:
        try:
            return await cast("ByteStream", self.s).receive(n)
        except (anyio.EndOfStream, anyio.BrokenResourceError, anyio.ClosedResourceError) as exc:
            raise EOFError from exc

    async def _handshake(self) -> None:
        ws = self._ws
        if ws is None:
            raise EOFError

        while True:
            closed = False
            ws.receive_data(await self._recv_raw())
            for event in ws.events():
                if isinstance(event, Request):
                    if self.path is not None and urlsplit(event.target).path != self.path:
                        await self._send_raw(ws.send(RejectConnection(status_code=404)))
                        raise EOFError
                    await self._send_raw(ws.send(AcceptConnection()))
                    return
                if isinstance(event, CloseConnection):
                    with suppress(EOFError):
                        await self._send_raw(ws.send(event.response()))
                    closed = True
                    break
            if closed:
                raise EOFError

    async def _reader(self):
        ws = self._ws
        if ws is None:
            return
        bbuf = bytearray()
        tbuf = []
        try:
            while True:
                ws.receive_data(await self._recv_raw())
                for event in ws.events():
                    if isinstance(event, BytesMessage):
                        if event.message_finished and not bbuf:
                            await self._b_send.send(bytes(event.data))
                        else:
                            bbuf.extend(event.data)
                            if event.message_finished:
                                await self._b_send.send(bytes(bbuf))
                                bbuf = bytearray()

                    elif isinstance(event, TextMessage):
                        if event.message_finished and not tbuf:
                            await self._t_send.send(event.data.encode("latin-1"))
                        else:
                            tbuf.append(event.data)
                            if event.message_finished:
                                await self._t_send.send("".join(tbuf).encode("latin-1"))
                                tbuf = []

                    elif isinstance(event, Ping):
                        await self._send_raw(ws.send(event.response()))

                    elif isinstance(event, CloseConnection):
                        with suppress(EOFError):
                            await self._send_raw(ws.send(event.response()))
                        return

        except EOFError:
            pass
        finally:
            with suppress(anyio.BrokenResourceError):
                await self._b_send.aclose()
            with suppress(anyio.BrokenResourceError):
                await self._t_send.aclose()

    async def snd(self, m: Buffer | bytes) -> None:  # noqa:D102
        ws = self._ws
        if ws is None:
            raise EOFError
        async with self._w_lock:
            await self._send_raw(ws.send(BytesMessage(data=bytes(m))))

    async def rcv(self) -> Buffer | bytes:  # noqa:D102
        try:
            return await self._b_recv.receive()
        except (anyio.EndOfStream, anyio.ClosedResourceError) as exc:
            raise EOFError from exc

    async def cwr(self, buf: Buffer) -> None:
        "Send console bytes as one websocket text message."
        ws = self._ws
        if ws is None:
            raise EOFError
        async with self._w_lock:
            await self._send_raw(ws.send(TextMessage(data=bytes(buf).decode("latin-1"))))

    async def crd(self, buf: MutBuffer) -> int:
        "Read console bytes from queued websocket text messages."
        while not self._crd_buf:
            try:
                self._crd_buf.extend(await self._t_recv.receive())
            except (anyio.EndOfStream, anyio.ClosedResourceError) as exc:
                raise EOFError from exc
        n = min(len(buf), len(self._crd_buf))
        buf[:n] = self._crd_buf[:n]
        self._crd_buf = self._crd_buf[n:]
        return n

    async def teardown(self):  # noqa:D102
        if self._ws is not None:
            with suppress(Exception):
                await self._send_raw(self._ws.send(CloseConnection(code=1000, reason="bye")))
        self._ws = None
        await super().teardown()


def ws_stack(stream, cfg: attrdict):
    """
    Build a message stack on top of a websocket block stream.
    """
    if not hasattr(stream, "snd") or not hasattr(stream, "rcv"):
        raise TypeError(f"need a BaseBlk not {stream}")

    link = cfg.get("link", {})
    lossy = link.get("lossy", None)
    log_cfg = cfg.get("log", None)
    log_rel = cfg.get("log_rel", None)
    log_raw = cfg.get("log_raw", None)

    if log_raw is not None:
        from moat.lib.stream import LogBlk  # noqa:PLC0415

        stream = LogBlk(stream, log_raw)

    from moat.lib.stream import CBORMsgBlk  # noqa:PLC0415

    stream = CBORMsgBlk(stream, cfg)

    if lossy:
        if lossy is True:
            lossy = {}
        from moat.lib.stream import ReliableMsg  # noqa:PLC0415

        if log_rel is not None:
            from moat.lib.stream import LogMsg  # noqa:PLC0415

            stream = LogMsg(stream, log_rel)

        stream = ReliableMsg(stream, lossy)

    if log_cfg is not None:
        from moat.lib.stream import LogMsg  # noqa:PLC0415

        stream = LogMsg(stream, log_cfg)

    return cast("BaseMsg", stream)
