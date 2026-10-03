"""
The MoaT Modbus client and its sub-objects (excluding individual bus values).
"""

from __future__ import annotations

import anyio
import logging
import socket
import struct
from anyio import ClosedResourceError, IncompleteRead
from anyio.abc import ByteStream, CancelScope, SocketAttribute, TaskGroup
from contextlib import asynccontextmanager, suppress
from functools import partial
from pathlib import Path as FSPath

from moat.util import CtxObj, Queue, ValueEvent
from moat.lib.modbus import ExcCodes, ExceptionResponse, FramerRTU, FramerTCP, ModbusIOError
from moat.util.exc import exc_iter, ungroup

from .types import MAX_REQ_LEN, BaseValue, DataBlock, TypeCodec

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio_serial import Serial

    from collections.abc import Callable
else:
    try:
        from anyio_serial import Serial
    except ImportError:
        Serial = None  # type:ignore[invalid-assignment]

_logger = logging.getLogger(__name__)

__all__ = [
    "ModbusClient",
    "ModbusError",
]

# seconds to wait when disconnecting/reconnecting TCP for different unitID
DISCONNECT_DELAY = 0.1
RECONNECT_TIMEOUT = 30

# RTU inter-frame timeout: if the framer's accumulator is non-empty
# (a prior handleFrame left used==0 with bytes still buffered) and no
# further bytes arrive within this window, the caller calls resetFrame()
# and drops the stale partial frame.
RTU_INTER_FRAME_TIMEOUT = 0.2


class ModbusClient(CtxObj):
    """The main bus handler. Use as:

    async with ModbusClient() as bus:
        ...
    """

    _tg: TaskGroup | None = None

    def __init__(self) -> None:
        self.hosts = {}

    @asynccontextmanager
    async def _ctx(self):
        async with anyio.create_task_group() as tg:
            self._tg = tg
            try:
                yield self
            finally:
                tg.cancel_scope.cancel()
                self._tg = None
                self.hosts = {}

    def host(self, addr, port=None, **kw):
        """Return a host object for connections to this address+port.

        You cannot create two host objects for the same destination.
        """
        if not port:
            port = 502
        if (addr, port) in self.hosts:
            raise KeyError(f"Host {addr}:{port} already exists")

        h = Host(self, addr, port, **kw)
        return h

    async def _host(self, addr, port=None, *, task_status) -> None:
        async with self.host(addr, port) as srv:
            task_status.started(srv)
            await anyio.sleep_forever()

    async def host_service(self, addr, port):
        """Run a TCP client in a background task."""
        if not port:
            port = 502
        assert self._tg is not None
        return await self._tg.start(self._host, addr, port)

    def serial(self, /, port, **ser):
        """Return a host object for connections to this serial port."""
        if port in self.hosts:
            raise KeyError(f"Host {port} already exists")

        h = SerialHost(self, port=port, **ser)
        return h

    async def _serial(self, /, port, ser, *, task_status) -> None:
        async with self.serial(port, **ser) as srv:
            task_status.started(srv)
            await anyio.sleep_forever()

    async def serial_service(self, port, **ser):
        """Run a serial client in a background task."""
        assert self._tg is not None
        return await self._tg.start(self._serial, port, ser)

    def conn(self, cfg):
        """Run a serial OR TCP client according to the config.

        @cfg is a dict with either host/port or port/serial keys.
        Returns a host.

        Usage::
            async with ModbusClient() as g, g.conn(cfg) as c, c.unit(cfg["unit"]) as u:
                ...
        """
        kw = {}
        for k in ("max_rd_len", "max_wr_len"):
            if k in cfg:
                kw[k] = cfg[k]

        if "serial" in cfg:
            port = cfg.get("port", None)
            kw.update(cfg["serial"])
            if port is not None:
                kw["port"] = port
            return self.serial(**kw)

        elif "host" in cfg or ("port" in cfg and isinstance(cfg["port"], int)):
            for k in ("host", "port"):
                with suppress(KeyError):
                    kw[k] = cfg[k]
            return self.host(**kw)
        else:
            raise ValueError("neither serial nor TCP config found")


class ModbusError(RuntimeError):
    """Error entry in returned datasets.

    Wraps a Modbus exception response (an :class:`~moat.lib.modbus.ExceptionResponse`)
    or, occasionally, another error object returned by the gateway.
    """

    def __init__(self, result) -> None:
        super().__init__(_explain(result))
        self.result = result

    @property
    def code(self) -> ExcCodes | None:
        """The Modbus exception code, or ``None`` if not an exception response."""
        if isinstance(self.result, ExceptionResponse):
            try:
                return ExcCodes(self.result.exception_code)
            except ValueError:
                return None
        return None

    @property
    def transient(self) -> bool:
        """Whether this error is worth retrying after a backoff.

        True for the “unit / target unavailable” family of Modbus exception
        codes (the gateway can\'t currently reach the slave) and for the
        “busy / acknowledged” codes that promise a later retry.  Permanent
        errors (illegal function/data) return ``False``.
        """
        return self.code in {
            ExcCodes.ACKNOWLEDGE,
            ExcCodes.SERVER_DEVICE_BUSY,
            ExcCodes.GATEWAY_PATH_UNAVAILABLE,
            ExcCodes.GATEWAY_TARGET_NO_RESPONSE,
        }


def _explain(result) -> str:
    """Render a human-readable description of a Modbus error result."""
    if isinstance(result, ExceptionResponse):
        try:
            code = ExcCodes(result.exception_code)
        except ValueError:
            return f"Modbus exception 0x{result.exception_code:02x}"
        hints = {
            ExcCodes.GATEWAY_PATH_UNAVAILABLE: "gateway path unavailable (unit not reachable)",
            ExcCodes.GATEWAY_TARGET_NO_RESPONSE: "gateway target not responding (unit not found)",
            ExcCodes.SERVER_DEVICE_FAILURE: "server/slave device failure",
            ExcCodes.SERVER_DEVICE_BUSY: "server/slave device busy",
            ExcCodes.ACKNOWLEDGE: "request acknowledged, retry later",
            ExcCodes.NEGATIVE_ACKNOWLEDGE: "negative acknowledge",
            ExcCodes.ILLEGAL_FUNCTION: "illegal function",
            ExcCodes.ILLEGAL_DATA_ADDRESS: "illegal data address",
            ExcCodes.ILLEGAL_DATA_VALUE: "illegal data value",
            ExcCodes.MEMORY_PARITY_ERROR: "memory parity error",
        }
        return hints.get(code, f"Modbus exception {code.name}")
    return f"Modbus error: {result!r}"


# Errors that mean "the host/unit is currently unreachable" — retry with
# backoff rather than hammering the gateway every cycle.
_TRANSIENT_EXC: tuple[type[BaseException], ...] = (
    OSError,  # connection refused, host unreachable, network down, ...
    TimeoutError,
    ClosedResourceError,
    anyio.BrokenResourceError,
    anyio.EndOfStream,
    IncompleteRead,
    ModbusIOError,
)


def _is_transient(exc: BaseException) -> bool:
    """Decide whether *exc* warrants an exponential backoff.

    True for transport-level reachability errors (host down, connection
    reset, timeout) and for the Modbus exception codes that signal a
    temporarily-unavailable slave/unit (gateway path / target no-response,
    device busy, acknowledge).
    """
    for e in exc_iter(exc):
        if isinstance(e, _TRANSIENT_EXC):
            return True
        if isinstance(e, ModbusError) and e.transient:
            return True
    return False


def _log_read_error(slot, exc: BaseException, *, backoff: bool) -> None:
    """Log a read error, unwrapping exception groups for clarity.

    The two nested task groups in :meth:`Slot.getValues`/:meth:`ValueList.readValues`
    wrap a single :class:`ModbusError` in two layers of ``ExceptionGroup``;
    showing those verbatim is useless.  Flatten to the underlying error(s)
    and report them directly, noting whether we\'ll back off.
    """
    errs = list(exc_iter(exc)) or [exc]
    for e in errs:
        if backoff:
            _logger.warning("Read error %s (retrying with backoff): %s", slot, e)
        else:
            _logger.error("Read error %s (not retried): %s", slot, e)


class HostCommon:
    stream: ByteStream | None = None
    framer: FramerTCP | FramerRTU  # set by subclasses in __init__
    _tg: TaskGroup | None = None
    _read_scope: CancelScope | None = None

    def _nextTID(self) -> int:
        raise NotImplementedError

    async def _reader(self, *, task_status) -> None:
        raise NotImplementedError

    _trace: Callable[..., None] = staticmethod(lambda *_x: None)  # overridden per-host

    def __init__(self, gate, timeout, cap) -> None:
        self.gate = gate
        self.units = {}
        self._wqueue = Queue(100)
        self._transactions = {}
        self._tid = 0
        self._tg = None
        self._read_scope = None
        self._connected = anyio.Event()

        self._send_lock = anyio.Lock()

        self.cap = anyio.CapacityLimiter(cap)
        self.timeout = timeout

    def unit(self, unit):
        """
        Returns the `Unit` object registered to nr. @unit.

        A new unit is allocated if it doesn't yet exist.
        """
        return Unit(self, unit)

    async def _unit(self, unit, *, task_status) -> None:
        async with self.unit(unit) as srv:
            task_status.started(srv)
            await anyio.sleep_forever()

    async def unit_scope(self, unit):
        """Run a unit in an `AsyncScope`"""
        # return await scope.service(f"MH_{num2id(self)}:{unit}", self._unit, unit)
        assert self._tg is not None
        return await self._tg.start(self._unit, unit)

    @property
    def _gate_key(self):
        raise NotImplementedError

    @asynccontextmanager
    async def _ctx(self):
        # might be used to manage the connection
        key = self._gate_key
        if key in self.gate.hosts:
            raise RuntimeError(f"Host {key} already exists")
        self.gate.hosts[key] = self

        try:
            async with anyio.create_task_group() as tg:
                self._tg = tg
                self._read_scope = tg.cancel_scope
                await tg.start(self._reader)

                yield self
                tg.cancel_scope.cancel()
        finally:
            self._tg = None
            if self.gate.hosts.get(key, None) is self:
                del self.gate.hosts[key]

    async def send(self, msg) -> None:
        """
        Send a packet.

        This is a low-level function. If you are a client, you want to use
        `execute` instead.
        """
        packet = self.framer.buildFrame(msg)
        await self._connected.wait()
        async with self._send_lock:
            assert self.stream is not None
            await self.stream.send(packet)

    async def execute(self, request):
        """
        Send a pymodbus request and wait for / return the reply.
        """
        # pylint: disable=logging-fstring-interpolation,protected-access

        request.transaction_id = self._nextTID()
        packet = self.framer.buildFrame(request)

        packet_info = " ".join([hex(x) for x in packet])
        self._trace("Gateway xmit: %s", packet_info)

        # make the modbus request
        async with self.cap:
            request._response_value = ValueEvent()  # noqa: SLF001

            await self._connected.wait()

            try:
                self._transactions[request.transaction_id] = request
                await self.send(request)
                with anyio.fail_after(self.timeout):
                    res = await request._response_value.get()  # noqa: SLF001

                if res.isError():
                    raise ModbusError(res)

                if hasattr(res, "registers"):
                    registers_info = " ".join([hex(x) for x in res.registers])
                    self._trace("Gateway replied: %s", registers_info)
                else:
                    self._trace("Gateway replied: %s", res)
                return res

            finally:
                self._transactions.pop(request.transaction_id, None)


class Host(HostCommon, CtxObj):
    """This is a single host which moat-modbus talks to.
    It has a number of modbus units (attribute 'units').

    Do not instantiate directly; instead, use

        >>> async with client.host("foo.example" [, port=20502] ) as host:
            ...
    """

    _tg = None

    def __init__(
        self,
        gate,
        addr,
        port,
        timeout=10,
        cap=1,
        debug=False,
        max_rd_len=MAX_REQ_LEN,
        max_wr_len=MAX_REQ_LEN,
    ) -> None:
        self.addr = addr
        self.port = port

        self.max_rd_len = max_rd_len
        self.max_wr_len = max_wr_len

        log = logging.getLogger(f"modbus.{addr}")
        self._trace = log.info if debug else log.debug

        self.framer = FramerTCP(False)

        super().__init__(gate, timeout, cap)

    def __repr__(self) -> str:
        return f"<ModbusHost:{self.addr}:{self.port}>"

    def _nextTID(self):
        self._tid = (self._tid + 1) % 0xFFFF
        return self._tid

    @property
    def _gate_key(self):
        return (self.addr, self.port)

    # reader task #

    async def _reader(self, *, task_status) -> None:
        # pylint: disable=protected-access

        async def _send_trans() -> None:
            tr = list(self._transactions.values())
            self._transactions = {}
            if tr:
                _logger.warning("Resend %d packets", len(tr))
            try:
                for request in tr:
                    packet = self.framer.buildFrame(request)
                    async with self._send_lock:
                        assert self.stream is not None
                        await self.stream.send(packet)
                if tr:
                    _logger.warning("Resend done")
            except Exception:  # pylint: disable=broad-except
                _logger.exception("Re-Write")

        # Signal readiness immediately: the host context is usable as soon
        # as the reader task is running.  Actual I/O gates on
        # ``self._connected`` (see ``send``/``execute``), so callers simply
        # wait until a connection succeeds.  This keeps the host alive when
        # the peer is unreachable at startup instead of crashing the daemon
        # via the ``tg.start(self._reader)`` handshake.
        if task_status is not None:
            task_status.started()
            task_status = None

        reconnect_delay = DISCONNECT_DELAY

        while True:
            connecting = self.stream is None
            try:
                if connecting:
                    with anyio.fail_after(self.timeout):
                        self.stream = await anyio.connect_tcp(self.addr, self.port)
                        # set so_linger to force sending RST instead of FIN
                        self.stream.extra(SocketAttribute.raw_socket).setsockopt(
                            socket.SOL_SOCKET,
                            socket.SO_LINGER,
                            struct.pack("ii", 1, 0),
                        )
                        # re-send open requests
                        await _send_trans()
                        self._connected.set()
                    self.framer.resetFrame()
                    # Up and healthy again: reset the reconnect backoff.
                    reconnect_delay = DISCONNECT_DELAY

                chunk = await self.stream.receive(4096)
                # pylint: disable=logging-not-lazy
                self._trace("recv: " + " ".join([hex(x) for x in chunk]))

                replies = []

                # Feed only the freshly-received bytes; the framer owns
                # the accumulator and retains any surplus internally.
                # Repeatedly call handleFrame with no new data to drain
                # every complete frame the chunk may contain.
                feed = bytes(chunk)
                while True:
                    used, pdu = self.framer.handleFrame(feed)
                    if pdu is not None:
                        replies.append(pdu)
                    if not used:
                        break
                    feed = b""

            except (
                IncompleteRead,
                OSError,  # incl. ConnectionRefused/Reset, host/network/DNS down
                ClosedResourceError,
                ModbusIOError,
                anyio.BrokenResourceError,
                anyio.EndOfStream,
                TimeoutError,
            ) as exc:
                if self._connected.is_set():
                    self._connected = anyio.Event()
                t, self._transactions = self._transactions, {}
                if t:
                    for req in t.values():
                        req._response_value.set_error(exc)  # noqa: SLF001
                elif connecting:
                    # Nothing was pending; the connect itself failed.
                    _logger.warning("Connect to %s:%d failed: %r", self.addr, self.port, exc)
                else:
                    _logger.error(
                        "Read from %s:%d: %r (%d)",
                        self.addr,
                        self.port,
                        exc,
                        len(self._transactions),
                    )

                s, self.stream = self.stream, None
                if s:
                    await s.aclose()

                # Brief pause after a dropped live connection; exponential
                # backoff (capped at RECONNECT_TIMEOUT) when the host is
                # unreachable, so we don't pound a downed gateway.
                if connecting:
                    reconnect_delay = min(
                        RECONNECT_TIMEOUT, max(DISCONNECT_DELAY, 1 + reconnect_delay * 1.3)
                    )
                else:
                    reconnect_delay = DISCONNECT_DELAY
                await anyio.sleep(reconnect_delay)

            except anyio.get_cancelled_exc_class():
                raise

            except BaseException as exc:
                _logger.exception("Error: %r", exc)  # noqa: TRY401

                t, self._transactions = self._transactions, {}
                for req in t.values():
                    req._response_value.set_error(exc)  # noqa: SLF001
                raise

            else:
                for reply in replies:
                    tid = reply.transaction_id
                    try:
                        request = self._transactions.pop(tid)
                    except KeyError:
                        _logger.info("Unrequested message: %s", reply)
                    else:
                        request._response_value.set(reply)  # noqa: SLF001

    async def aclose(self) -> None:
        """Stop talking."""
        if self.gate is None:
            return
        self.gate._del_host(self)  # pylint: disable=protected-access  # noqa: SLF001
        self.gate = None

        u, self.units = self.units, None
        for unit in u.values():
            await unit.aclose()

        if self._read_scope is not None:
            self._read_scope.cancel()
            self._read_scope = None

        s, self.stream = self.stream, None
        if s:
            await s.aclose()


class SerialHost(HostCommon, CtxObj):
    """This is a "host" that's actually a serial interface.

    Do not instantiate directly; instead, use

        >>> async with client.serial("/dev/ttyUSB0",
                baudrate=9600, parity="E", stopbits=1) as host:
            ...
    """

    _tg = None

    def __init__(
        self,
        gate,
        /,
        port,
        timeout=10,
        debug=False,
        monitor=None,
        max_rd_len=MAX_REQ_LEN,
        max_wr_len=MAX_REQ_LEN,
        **ser,
    ) -> None:
        self.port = port
        self.ser = ser
        self.framer = FramerRTU(False)
        self.max_rd_len = max_rd_len
        self.max_wr_len = max_wr_len

        log = logging.getLogger(f"modbus.{FSPath(port).name}")
        self._trace = log.info if debug else log.debug
        self._monitor = monitor

        super().__init__(gate, timeout, 1)

    def __repr__(self) -> str:
        return f"<ModbusHost:{self.port}:{self.ser.get('baudrate', 0)}>"

    def _nextTID(self) -> int:
        return 0

    @property
    def _gate_key(self):
        return self.port

    # reader task #

    async def _reader(self, *, task_status) -> None:
        # pylint: disable=protected-access

        if self._transactions:
            raise RuntimeError("Serial: cannot have open transaction on start")
        if Serial is None:
            raise RuntimeError("You need to install anyio_serial")

        task_status.started()
        self._trace("recv START")

        mon = self._monitor
        while True:
            try:
                async with ungroup, Serial(port=self.port, **self.ser) as self.stream:
                    self._connected.set()
                    self.framer.resetFrame()
                    while True:
                        try:
                            if self.framer.pending:
                                # A partial frame is in progress: bound
                                # the wait so a torn frame or a silent
                                # slave is recovered via resetFrame(),
                                # not held forever.
                                with anyio.fail_after(RTU_INTER_FRAME_TIMEOUT):
                                    chunk = await self.stream.receive(4096)
                            else:
                                chunk = await self.stream.receive(4096)
                        except TimeoutError:
                            # Inter-frame timeout: the framer accumulator
                            # is non-empty but no more bytes arrived within
                            # the window.  Drop the stale partial frame and
                            # continue — do NOT tear down the connection.
                            self.framer.resetFrame()
                            continue

                        # pylint: disable=logging-not-lazy
                        self._trace("recv: " + " ".join([hex(x) for x in chunk]))

                        replies = []

                        # Feed only the freshly-received bytes; the framer
                        # owns the accumulator and retains any surplus
                        # internally.  Repeatedly call handleFrame with no
                        # new data to drain every complete frame the chunk
                        # may contain.
                        feed = bytes(chunk)
                        while True:
                            used, pdu = self.framer.handleFrame(feed)
                            if pdu is not None:
                                replies.append(pdu)
                            if not used:
                                break
                            feed = b""

                        if mon:
                            for reply in replies:
                                await mon(reply)
                        else:
                            for reply in replies:
                                tid = reply.transaction_id
                                try:
                                    request = self._transactions.pop(tid)
                                except KeyError:
                                    _logger.info("Unrequested message: %s", reply)
                                else:
                                    request._response_value.set(reply)  # noqa: SLF001

            except (
                IncompleteRead,
                ConnectionRefusedError,
                ConnectionResetError,
                ClosedResourceError,
                ModbusIOError,
                anyio.BrokenResourceError,
                anyio.EndOfStream,
            ) as exc:
                if self._connected.is_set():
                    self._connected = anyio.Event()
                _logger.error("Read: %r (%d)", exc, len(self._transactions))

                t, self._transactions = self._transactions, {}
                for req in t.values():
                    req._response_value.set_error(exc)  # noqa: SLF001

            except anyio.get_cancelled_exc_class():
                raise

            except BaseException as exc:
                _logger.exception("Error: %r", exc)  # noqa: TRY401

                t, self._transactions = self._transactions, {}
                for req in t.values():
                    req._response_value.set_error(exc)  # noqa: SLF001
                raise

    async def aclose(self) -> None:
        """Stop talking."""
        if self.gate is None:
            return
        self.gate._del_host(self)  # pylint: disable=protected-access  # noqa: SLF001
        self.gate = None

        u, self.units = self.units, None
        for unit in u.values():
            await unit.aclose()

        if self._read_scope is not None:
            self._read_scope.cancel()
            self._read_scope = None

        s, self.stream = self.stream, None
        if s:
            await s.aclose()


class Unit(CtxObj):
    """This is a single modbus unit. It has any number of time slots
    (attribute 'slots'). Simply indexing a unit will return a timeslot
    object (existing or new). You can use anything hashable as the index.

    Units are always linked to a host. Use

        >>> async with host.unit(1) as u:
            ...

    to access/create a unit.
    """

    _running = False

    def __init__(self, host, unit) -> None:
        self.host = host
        self.unit = unit
        self.slots = {}

    def __str__(self) -> str:
        try:
            return f"{self.host.addr}:{self.host.port}:{self.unit}"
        except AttributeError:
            return f"{self.host.port}:{self.unit}"

    def __repr__(self) -> str:
        try:
            return f"<Unit:{self.host.addr}:{self.host.port}:{self.unit}>"
        except AttributeError:
            return f"<Unit:{self.host.port}:{self.unit}>"

    @asynccontextmanager
    async def _ctx(self):
        if self._running:
            raise RuntimeError(f"Slot {self.slot} already active")
        self._running = True
        try:
            async with anyio.create_task_group() as tg:
                self._tg = tg
                yield self
                tg.cancel_scope.cancel()
        finally:
            self._tg = None
            self._running = False
            self.host.units.pop(self.unit, None)

    def slot(self, slot, **kw):
        """
        Returns the `Slot` object registered to @slot.

        A new slot is allocated if it doesn't yet exist.
        """
        try:
            return self.slots[slot]
        except KeyError:
            self.slots[slot] = sl = Slot(self, slot, **kw)
            return sl

    async def _slot(self, slot, kw, *, task_status) -> None:
        async with self.slot(slot, **kw) as srv:
            task_status.started(srv)
            await anyio.sleep_forever()

    async def slot_scope(self, slot, **kw):
        """Run the slot handler in an AsyncScope."""
        # return await scope.service(f"MS_{num2id(self)}:{slot}", self._slot, slot, **kw)
        return await self._tg.start(self._slot, slot, kw)

    async def aclose(self) -> None:
        """Stop talking and delete yourself.

        This is a coroutine.
        """
        if self.host is None:
            return
        self.host._del_unit(self)  # pylint: disable=protected-access  # noqa: SLF001
        self.host = None

        s, self.slots = self.slots, None
        for slot in s.values():
            await slot.aclose()

    async def process_request(self, request):
        """
        Forward a request to the host.
        """
        request.unit_id = self.unit
        try:
            response = await self.host.execute(request)
        except Exception as exc:
            _logger.exception("Handler for %d: %r", self.unit, exc)  # noqa: TRY401
            response = ExceptionResponse(request.function_code, ExcCodes.DEVICE_FAILURE)

        return response


class Slot(CtxObj):
    """This class represents a single "atomic" access to Modbus. The system
    will periodically try to fetch all values in this slot, using as
    few+small requests as possible.

    Slots are always linked to a unit. Use

        >>> async with unit.slot("20seconds") as slot:
            ...

    to access/create a slot.

    The intended usecase is that some values should be retrieved at
    different intervals than others. Thus the user creates several slots
    and adds the required fields to them.

    Slots will periodically read registers,

    Slots will write updated holding registers, delaying for @write_delay
    for possible collation.
    """

    _get_scope: CancelScope | None = None
    _set_scope: CancelScope | None = None
    delay: float | None = None
    t_read: float | None = None
    _scope: CancelScope | None = None
    _running = False

    def __init__(
        self,
        unit: Unit,
        slot: str,
        read_delay: float | None = None,
        read_align: bool = False,
        write_delay: float | None = None,
        age: float | None = None,
        **kw,
    ) -> None:
        self.unit = unit
        self.slot = slot

        self.write_delay = write_delay
        self.write_lock = anyio.Lock()
        self.write_trigger = anyio.Event()

        self.read_delay = read_delay
        self.read_align = read_align
        self.age = age
        self.read_lock = anyio.Lock()
        self.read_trigger = anyio.Event()

        self.run_lock: anyio.Event | None = None

        self.modes = {}
        self.mqtt_registers = set()  # Link Registers with dest configured
        if kw:
            _logger.warning("%s:%s: extra arguments: %r", unit, slot, kw)

    def __str__(self) -> str:
        return f"{self.unit}:{self.slot}"

    def __repr__(self) -> str:
        return f"<Unit:{self.unit}:{self.slot}>"

    @asynccontextmanager
    async def _ctx(self):
        if self._running:
            raise RuntimeError(f"Slot {self.slot} already active")
        self._running = True
        try:
            async with anyio.create_task_group() as tg:
                self._scope = tg.cancel_scope
                self.run_lock = anyio.Event()
                if self.write_delay is not None:
                    tg.start_soon(self.write_task)
                if self.read_delay is not None:
                    tg.start_soon(self.read_task)
                yield self
                tg.cancel_scope.cancel()
        finally:
            self.run_lock = None
            self._running = False
            del self.unit.slots[self.slot]

    def start(self) -> None:
        """
        Start running this slot.
        """
        self.run_lock.set()

    def trigger_send(self) -> None:
        """Start writing after at most `.write_delay` seconds."""
        self.write_trigger.set()

    @property
    def is_empty(self):
        """
        Check whether the slot does not contain any registers.
        """
        return all(not offsets.values for offsets in self.modes.values())

    def add(self, typ: TypeCodec, offset: int, cls: type[BaseValue] | BaseValue) -> BaseValue:
        """Add a field to this slot.

        :param typ: The `TypeCodec` instance to use.
        :param offset: The value's numeric offset, zero-based.
        :param val: The data type (baseValue instance)

        `cls` is the decoder (subclass of `BaseValue`).
        """
        try:
            k = self.modes[typ]
        except KeyError:
            self.modes[typ] = k = ValueList(self, typ)
        val = cls(offset=offset) if isinstance(cls, type) else cls
        k.add(offset, val)
        return val

    def remove(self, typ: TypeCodec, offset: int):
        """Remove a field to be requested.

        :param typ: the `TypeCodec` to use
        :param offset: the offset where the value is located

        Returns the field in question, or none if it doesn't exist.
        """
        try:
            k = self.modes[typ]
        except KeyError:
            return None
        return k.delete(offset)

    async def _stop_run(self) -> None:
        if self._get_scope is not None:
            self._get_scope.cancel()
        if self._set_scope is not None:
            self._set_scope.cancel()

    def close(self) -> None:
        """
        Close this slot.
        """
        if self._scope is None:
            return
        self._scope.cancel()

    async def getValues(self) -> dict[TypeCodec, dict[int, Any]]:
        """
        Send messages reading this slot's values from the bus.
        Returns a (type,(offset,value)) dict-of-dicts.
        On error, stores the error object instead of a dict.

        This method may return a partial result.
        """
        try:
            res = {}

            async def _assign(getter, rr) -> None:
                r = await getter()
                rr.update(r)

            async with anyio.create_task_group() as tg:
                if self._get_scope is not None:
                    raise RuntimeError("already running")
                self._get_scope = tg.cancel_scope

                for typ, vl in self.modes.items():
                    res[typ] = r = {}
                    try:
                        tg.start_soon(partial(_assign, vl.readValues, r))
                    except ModbusError as r:
                        res[typ] = r.result

            if self.unit is None:
                raise ClosedResourceError("dropped while running")
            return res
        finally:
            self._get_scope = None

    async def setValues(self, changed=False) -> None:
        """
        Send a message writing the values in this block to the bus.
        """
        try:
            async with anyio.create_task_group() as tg:
                if self._set_scope is not None:
                    raise RuntimeError("already running")
                self._set_scope = tg.cancel_scope

                for vl in self.modes.values():
                    tg.start_soon(vl.writeValues, changed)
            if self.unit is None:
                raise ClosedResourceError("dropped while running")
        finally:
            self._set_scope = None

    async def read(self):
        """Read this slot's data."""
        async with self.read_lock:
            self.t_read = anyio.current_time()
            return await self.getValues()

    async def read_if_stale(self) -> bool:
        """Read this slot's data only if it's stale (older than age).

        Returns True if a read was performed, False if data was fresh.
        Caller must hold self.read_lock.
        """
        if self.age is not None:
            assert self.t_read is not None
            current_time = anyio.current_time()
            age_threshold = self.t_read + self.age
            if current_time < age_threshold:
                _logger.debug(
                    "%s: data fresh (age %.1fs < %.1fs)",
                    self,
                    current_time - self.t_read,
                    self.age,
                )
                return False  # Data is fresh enough
            _logger.debug(
                "%s: data stale (age %.1fs >= %.1fs), re-reading",
                self,
                current_time - self.t_read,
                self.age,
            )

        # Data is stale or no age limit, perform read
        self.t_read = anyio.current_time()
        await self.getValues()
        return True

    async def read_task(self) -> None:
        """A background task for reading Modbus register values.
        We read every .`read_delay` seconds.

        Transport errors (host unreachable, connection reset) and Modbus
        “unit not available” exception codes trigger an exponential
        backoff so we don\'t pound an offline gateway every cycle;
        permanent protocol errors (illegal function/address/value) are
        logged prominently but otherwise keep the regular cadence.
        """
        await self.run_lock.wait()

        try:
            await self.read()
        except Exception as exc:  # pylint:disable=broad-except
            _log_read_error(self, exc, backoff=False)
        else:
            # Notify MQTT tasks after initial read
            for reg in self.mqtt_registers:
                if reg.reg._changed:  # noqa: SLF001  # Flag set by BaseValue.decode
                    _logger.debug("%s: notifying %s after initial read", self, reg.path)
                    reg.reg._changed = False  # noqa: SLF001
                    reg.mqtt_event.set()

        tn = self.t_read + self.read_delay
        if self.read_align:
            tn -= tn % self.read_delay

        backoff = 0.0

        while True:
            t = anyio.current_time()
            tr = self.t_read
            if t < tn + backoff:
                await anyio.sleep(tn + backoff - t)

            async with self.read_lock:
                if self.t_read != tr:
                    # somebody else has read while we waited for the lock
                    tn = self.t_read + self.read_delay
                    if self.read_align:
                        tn -= tn % self.read_delay
                    continue

                # Determine if we're on schedule or late
                if t < tn:
                    # We slept, update next target time
                    tn_next = tn + self.read_delay
                else:
                    # We didn't sleep: the last read took too long. reset the timer
                    _logger.info(
                        "Delay for %s: %.1f > %.1f",
                        self,
                        t - tn + self.read_delay,
                        self.read_delay,
                    )
                    tn_next = t + self.read_delay
                    if self.read_align:
                        tn_next -= tn_next % self.read_delay

                try:
                    did_read = await self.read_if_stale()
                except Exception as exc:  # pylint:disable=broad-except
                    transient = _is_transient(exc)
                    _log_read_error(self, exc, backoff=transient)
                    if transient:
                        # Exponential backoff, capped at ~1 minute.
                        backoff = min(60, 1 + backoff * 1.5)
                    else:
                        raise
                else:
                    backoff = 0
                    # Only update t_read if we actually read
                    if did_read:
                        tn = tn_next
                    else:
                        # Data was fresh, keep checking at regular intervals
                        tn = tn_next

                # Always check and notify changed registers
                # (may have been set by server-triggered read without notification)
                for reg in self.mqtt_registers:
                    if reg.reg._changed:  # noqa: SLF001  # Flag set by BaseValue.decode
                        _logger.debug("%s: notifying %s (changed)", self, reg.path)
                        reg.reg._changed = False  # noqa: SLF001
                        reg.mqtt_event.set()

    async def write(self, changed: bool = True) -> None:
        """Write this slot's data.

        If @changed is set, only write changed data.
        """
        async with self.write_lock:
            await self.setValues(changed=changed)

    async def write_task(self) -> None:
        """A background task for updating changed Modbus register values"""
        await self.run_lock.wait()
        while True:
            await self.write_trigger.wait()
            await anyio.sleep(1)  # self.write_delay)
            self.write_trigger = anyio.Event()
            try:
                await self.write(changed=True)
            except ModbusError:
                _logger.exception("Write %s", self)
                # TODO examine+record the error


class ValueList(DataBlock):
    """This class holds a list of to-be-accessed values.

    Do not instantiate directly; constructed and returned by

        >>> slot.add(InputRegisters, 2, IntValue)

    """

    slot: Slot | None

    def __init__(self, slot: Slot, kind: TypeCodec) -> None:
        super().__init__(
            max_rd_len=slot.unit.host.max_rd_len,
            max_wr_len=slot.unit.host.max_wr_len,
        )
        self.slot = slot
        self.kind = kind
        self.do_write = anyio.Event()

    def trigger_send(self) -> None:
        assert self.slot is not None
        self.slot.trigger_send()

    async def readValues(self, *, res=None):
        """
        Send messages reading these values to the bus.

        Returns a (offset,value) dict.
        """
        if res is None:
            res = {}
        async with anyio.create_task_group() as tg:
            for start, length in self.ranges(max_len=self.max_rd_len):
                tg.start_soon(partial(self.readBlock, start, length, res=res))
        return res

    async def writeValues(self, changed=False) -> None:
        """
        Send messages writing our values to the bus.
        """
        async with anyio.create_task_group() as tg:
            for start, length in self.ranges(changed=changed, max_len=self.max_wr_len):
                tg.start_soon(partial(self.writeBlock, start, length))

    async def readBlock(self, start, length, *, res=None) -> None:
        """Send one message, decode the reply"""
        if res is None:
            res = {}
        assert self.slot is not None
        u = self.slot.unit
        msg = self.kind.encoder(address=start, count=length, unit_id=u.unit)

        r = await u.host.execute(msg)

        # TODO check R for correct type?

        r = r.registers

        while r:
            try:
                val = self[start]
            except KeyError:
                off = 1
            else:
                off = val.len
                val.decode(r[:off])
                res[start] = val
            start += off
            r = r[off:]

    async def writeBlock(self, start, length) -> None:
        """encode one message and send it"""
        assert self.slot is not None
        u = self.slot.unit
        values = []
        off = start
        res = length
        while res > 0:
            val = self[off]
            values.extend(val.encode())
            off += val.len
            res -= val.len
        if len(values) == 1:
            msg = self.kind.encoder_s(address=start, unit_id=u.unit, registers=values)
        else:
            msg = self.kind.encoder_m(
                address=start, count=length, unit_id=u.unit, registers=values
            )

        await u.host.execute(msg)  # pylint: disable=unused-variable
        # raises an error if failed

        self.markSent(start, length)

    def close(self) -> None:
        """disable further accesses"""
        if self.slot is None:
            return
        self.slot = None
