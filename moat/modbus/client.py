"""
The MoaT Modbus client and its sub-objects (excluding individual bus values).
"""

from __future__ import annotations

import logging
import socket
import struct
from contextlib import asynccontextmanager, suppress
from functools import partial
from pathlib import Path
from typing import Any

import anyio
from anyio import ClosedResourceError, IncompleteRead
from anyio.abc import SocketAttribute
from anyio_serial import Serial
from moat.util import CtxObj, Queue, ValueEvent, num2id
from moat.util.exc import ungroup
from pymodbus.exceptions import ModbusIOException
from pymodbus.pdu import DecodePDU, ExceptionResponse
from pymodbus.framer import FramerRTU, FramerSocket

from .types import BaseValue, DataBlock, TypeCodec, MAX_REQ_LEN

_logger = logging.getLogger(__name__)

__all__ = [
    "ModbusClient",
    "ModbusError",
]

# seconds to wait when disconnecting/reconnecting TCP for different unitID
DISCONNECT_DELAY = 0.1
RECONNECT_TIMEOUT = 10
CHECK_STREAM_TIMEOUT = 0.001


class ModbusClient(CtxObj):
    """The main bus handler. Use as
    >>> async with ModbusClient() as bus:
        ...
    """

    _tg = None

    def __init__(self):
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

    async def _host(self, addr, port=None, *, task_status):
        async with self.host(addr, port) as srv:
            task_status.started(srv)
            await anyio.sleep_forever()

    async def host_service(self, addr, port):
        """Run a TCP client in an AsyncScope."""
        if not port:
            port = 502
        #return await scope.service(f"MC_{num2id(self)}:{addr}:{port}", self._host, addr, port)
        return await self._tg.start(self._host,addr,port)

    def serial(self, /, port, **ser):
        """Return a host object for connections to this serial port."""
        if port in self.hosts:
            raise KeyError(f"Host {port} already exists")

        h = SerialHost(self, port=port, **ser)
        return h

    async def _serial(self, /, port, ser, *, task_status):
        async with self.serial(port, **ser) as srv:
            task_status.started(srv)
            await anyio.sleep_forever()

    async def serial_service(self, port, **ser):
        """Run a serial client in an AsyncScope."""
        # return await scope.service(f"MC_{num2id(self)}:{port}", self._serial, port, **ser)
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
    """Error entry in returned datasets"""

    def __init__(self, result):
        super().__init__()
        self.result = result


class _HostCommon:
    stream = None
    framer = None  # overridden
    _trace = lambda *x: None  # pylint:disable=unnecessary-lambda-assignment  #  overridden

    def __init__(self, gate, timeout, cap):
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

    async def _unit(self, unit, *, task_status):
        async with self.unit(unit) as srv:
            task_status.started(srv)
            await anyio.sleep_forever()

    async def unit_scope(self, unit):
        """Run a unit in an `AsyncScope`"""
        # return await scope.service(f"MH_{num2id(self)}:{unit}", self._unit, unit)
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

    async def send(self, msg):
        """
        Send a packet.

        This is a low-level function. If you are a client, you want to use
        `execute` instead.
        """
        packet = self.framer.buildFrame(msg)
        await self._connected.wait()
        async with self._send_lock:
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
            request._response_value = ValueEvent()

            await self._connected.wait()

            try:
                self._transactions[request.transaction_id] = request
                await self.send(request)
                with anyio.fail_after(self.timeout):
                    res = await request._response_value.get()

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


class Host(_HostCommon, CtxObj):
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
    ):
        self.addr = addr
        self.port = port

        self.max_rd_len = max_rd_len
        self.max_wr_len = max_wr_len

        log = logging.getLogger(f"modbus.{addr}")
        self._trace = log.info if debug else log.debug

        self.framer = FramerSocket(DecodePDU(False))

        super().__init__(gate, timeout, cap)

    def __repr__(self):
        return f"<ModbusHost:{self.addr}:{self.port}>"

    def _nextTID(self):
        self._tid = (self._tid + 1) % 0xFFFF
        return self._tid

    @property
    def _gate_key(self):
        key = (self.addr, self.port)

    # reader task #

    async def _reader(self, *, task_status):
        # pylint: disable=protected-access

        async def _send_trans():
            tr = list(self._transactions.values())
            self._transactions = {}
            if tr:
                _logger.warning("Resend %d packets", len(tr))
            try:
                for request in tr:
                    packet = self.framer.buildFrame(request)
                    async with self._send_lock:
                        await self.stream.send(packet)
                if tr:
                    _logger.warning("Resend done")
            except Exception:  # pylint: disable=broad-except
                _logger.exception("Re-Write")

        data = bytearray()

        while True:
            try:
                if self.stream is None:
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
                        if task_status is not None:
                            task_status.started()
                            task_status = None
                    data = bytearray()

                data += await self.stream.receive(4096)
                # pylint: disable=logging-not-lazy
                self._trace("recv: " + " ".join([hex(x) for x in data]))

                replies = []

                while True:
                    used, pdu = self.framer.processIncomingFrame(data)
                    data = data[used:]
                    if pdu is not None:
                        replies.append(pdu)
                    if not used:
                        break

            except (
                IncompleteRead,
                ConnectionRefusedError,
                ConnectionResetError,
                ClosedResourceError,
                ModbusIOException,
                anyio.BrokenResourceError,
                anyio.EndOfStream,
                TimeoutError,
            ) as exc:
                if self._connected.is_set():
                    self._connected = anyio.Event()
                t, self._transactions = self._transactions, {}
                if t:
                    for req in t.values():
                        req._response_value.set_error(exc)
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

                # delay somewhat, to give the device the chance to reinitialize
                await anyio.sleep(DISCONNECT_DELAY)

            except anyio.get_cancelled_exc_class():
                raise

            except BaseException as exc:
                _logger.exception("Error: %r", exc)

                t, self._transactions = self._transactions, {}
                for req in t.values():
                    req._response_value.set_error(exc)
                raise

            else:
                for reply in replies:
                    tid = reply.transaction_id
                    try:
                        request = self._transactions.pop(tid)
                    except KeyError:
                        _logger.info("Unrequested message: %s", reply)
                    else:
                        request._response_value.set(reply)

    async def aclose(self):
        """Stop talking."""
        if self.gate is None:
            return
        self.gate._del_host(self)  # pylint: disable=protected-access
        self.gate = None

        u, self.units = self.units, None
        for unit in u.values():
            await unit.aclose()

        if self._read_scope is not None:
            self._read_scope.cancel()
            self._read_scope = None

        s, self.stream = self.stream, None
        if s:
            await s.close()


class SerialHost(_HostCommon, CtxObj):
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
    ):
        self.port = port
        self.ser = ser
        self.framer = FramerRTU(DecodePDU(False))
        self.max_rd_len = max_rd_len
        self.max_wr_len = max_wr_len

        log = logging.getLogger(f"modbus.{Path(port).name}")
        self._trace = log.info if debug else log.debug
        self._monitor = monitor

        super().__init__(gate, timeout, 1)

    def __repr__(self):
        return f"<ModbusHost:{self.port}:{self.ser.get('baudrate', 0)}>"

    def _nextTID(self):
        return 0

    @property
    def _gate_key(self):
        key = self.port

    # reader task #

    async def _reader(self, *, task_status):
        # pylint: disable=protected-access

        if self._transactions:
            raise RuntimeError("Serial: cannot have open transaction on start")
        task_status.started()
        self._trace("recv START")

        mon = self._monitor
        data = bytearray()
        while True:
            try:
                async with ungroup, Serial(port=self.port, **self.ser) as self.stream:
                    self._connected.set()
                    while True:

                        if data:
                            with anyio.fail_after(self.timeout):
                                data += await self.stream.receive(4096)
                        else:
                            data = await self.stream.receive(4096)

                        # pylint: disable=logging-not-lazy
                        self._trace("recv: " + " ".join([hex(x) for x in data]))

                        replies = []

                        # check for decoding errors
                        while True:
                            used, pdu = self.framer.processIncomingFrame(data)
                            if pdu is not None:
                                replies.append(pdu)
                            if not used:
                                break
                            data = data[used:]

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
                                    request._response_value.set(reply)

            except (
                IncompleteRead,
                ConnectionRefusedError,
                ConnectionResetError,
                ClosedResourceError,
                ModbusIOException,
                anyio.BrokenResourceError,
                anyio.EndOfStream,
                TimeoutError,
            ) as exc:
                if self._connected.is_set():
                    self._connected = anyio.Event()
                _logger.error("Read: %r (%d)", exc, len(self._transactions))

                t, self._transactions = self._transactions, {}
                for req in t.values():
                    req._response_value.set_error(exc)

            except anyio.get_cancelled_exc_class():
                raise

            except BaseException as exc:
                _logger.exception("Error: %r", exc)

                t, self._transactions = self._transactions, {}
                for req in t.values():
                    req._response_value.set_error(exc)
                raise


    async def aclose(self):
        """Stop talking."""
        if self.gate is None:
            return
        self.gate._del_host(self)  # pylint: disable=protected-access
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

    def __init__(self, host, unit):
        self.host = host
        self.unit = unit
        self.slots = {}

    def __str__(self):
        try:
            return f"{self.host.addr}:{self.host.port}:{self.unit}"
        except AttributeError:
            return f"{self.host.port}:{self.unit}"

    def __repr__(self):
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

    async def _slot(self, slot, kw, *, task_status):
        async with self.slot(slot, **kw) as srv:
            task_status.started(srv)
            await anyio.sleep_forever()

    async def slot_scope(self, slot, **kw):
        """Run the slot handler in an AsyncScope."""
        # return await scope.service(f"MS_{num2id(self)}:{slot}", self._slot, slot, **kw)
        return await self._tg.start(self._slot, slot, kw)

    async def aclose(self):
        """Stop talking and delete yourself.

        This is a coroutine.
        """
        if self.host is None:
            return
        self.host._del_unit(self)  # pylint: disable=protected-access
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
            logger.exception("Handler for %d: %r", unit_id, exc)
            response = ExceptionResponse(request.function_code, ExceptionResponse.SLAVE_FAILURE)

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

    _get_scope = None
    _set_scope = None
    delay: float = None
    t_read = None
    _scope = None
    _running = False

    def __init__(
        self,
        unit,
        slot,
        read_delay: float | None = None,
        read_align: bool = False,
        write_delay: float | None = None,
        **kw,
    ):
        self.unit = unit
        self.slot = slot

        self.write_delay = write_delay
        self.write_lock = anyio.Lock()
        self.write_trigger = anyio.Event()

        self.read_delay = read_delay
        self.read_align = read_align
        self.read_lock = anyio.Lock()
        self.read_trigger = anyio.Event()

        self.run_lock: anyio.Event = None

        self.modes = {}
        if kw:
            _logger.warning("%s:%s: extra arguments: %r", unit, slot, kw)

    def __str__(self):
        return f"{self.unit}:{self.slot}"

    def __repr__(self):
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

    def start(self):
        """
        Start running this slot.
        """
        self.run_lock.set()

    def trigger_send(self):
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

    async def _stop_run(self):
        if self._get_scope is not None:
            await self._get_scope.cancel()
        if self._set_scope is not None:
            await self._set_scope.cancel()

    def close(self):
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

            async def _assign(getter, rr):
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

    async def setValues(self, changed=False):
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
            await self.getValues()

    async def read_task(self):
        """A background task for reading Modbus register values.
        We read every .`read_delay` seconds.
        """
        await self.run_lock.wait()

        try:
            await self.read()
        except Exception as exc:  # pylint:disable=broad-except
            _logger.warning("Error %s: %r", self, exc)
        tn = self.t_read + self.read_delay
        if self.read_align:
            tn -= tn % self.read_delay

        backoff = 0

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
                if t < tn:
                    # We slept, above, thus update the current time
                    self.t_read = tn
                    tn += self.read_delay
                else:
                    # We didn't sleep: the last read took too long. reset the timer
                    _logger.info(
                        "Delay for %s: %.1f > %.1f",
                        self,
                        t - tn + self.read_delay,
                        self.read_delay,
                    )

                    self.t_read = t = anyio.current_time()
                    tn = t + self.read_delay
                    if self.read_align:
                        tn -= tn % self.read_delay

                try:
                    await self.getValues()  # already locked
                except Exception as exc:  # pylint:disable=broad-except
                    _logger.warning("Error %s: %r", self, exc)
                    backoff = 1 + backoff * 1.2
                    # TODO re-raise if persistent?
                else:
                    backoff = 0

    async def write(self, changed: bool = True):
        """Write this slot's data.

        If @changed is set, only write changed data.
        """
        async with self.write_lock:
            await self.setValues(changed=changed)

    async def write_task(self):
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

    def __init__(self, slot, kind):
        super().__init__(
            max_rd_len=slot.unit.host.max_rd_len,
            max_wr_len=slot.unit.host.max_wr_len,
        )
        self.slot = slot
        assert hasattr(kind, "encoder_m")
        self.kind = kind
        self.do_write = anyio.Event()

    def trigger_send(self):
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

    async def writeValues(self, changed=False):
        """
        Send messages writing our values to the bus.
        """
        async with anyio.create_task_group() as tg:
            for start, length in self.ranges(changed=changed, max_len=self.max_wr_len):
                tg.start_soon(partial(self.writeBlock, start, length))

    async def readBlock(self, start, length, *, res=None):
        """Send one message, decode the reply"""
        if res is None:
            res = {}
        u = self.slot.unit
        msg = self.kind.encoder(address=start, count=length, dev_id=u.unit)

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

    async def writeBlock(self, start, length):
        """encode one message and send it"""
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
            msg = self.kind.encoder_s(address=start, dev_id=u.unit, registers=values)
        else:
            msg = self.kind.encoder_m(address=start, count=length, dev_id=u.unit, registers=values)

        await u.host.execute(msg)  # pylint: disable=unused-variable
        # raises an error if failed

        self.markSent(start, length)

    def close(self):
        """disable further accesses"""
        if self.slot is None:
            return
        self.slot = None
        self.values = None
