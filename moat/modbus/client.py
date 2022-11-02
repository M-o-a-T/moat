"""
modbus access
"""
import logging
import socket
import struct
from contextlib import asynccontextmanager
from functools import partial
from typing import Any, Dict, Type

import anyio
from anyio import ClosedResourceError, IncompleteRead
from anyio.abc import SocketAttribute
from moat.util import CtxObj, Queue, ValueEvent
from pymodbus.exceptions import ModbusIOException
from pymodbus.factory import ClientDecoder
from pymodbus.transaction import ModbusSocketFramer

from .types import BaseValue, DataBlock, TypeCodec

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
    `async with ModbusClient() as bus:`.
    """

    _tg = None

    def __init__(self):
        self.hosts = {}

    @asynccontextmanager
    async def _ctx(self):
        async with anyio.create_task_group() as self._tg:
            try:
                yield self
            finally:
                tg, self._tg = self._tg, None
                self.hosts = {}
                tg.cancel_scope.cancel()

    def host(self, addr, port=502):
        """Return a host object for connections to this address+port.
        The host will be created if it has not been seen before.
        """
        try:
            return self.hosts[(addr, port)]
        except KeyError:
            return Host(self, addr, port)

    def _del_host(self, host):
        del self.hosts[(host.addr, host.port)]


class ModbusError(RuntimeError):
    """Error entry in returned datasets"""

    def __init__(self, result):
        super().__init__()
        self.result = result


class Host:
    """This is a single host which moat-modbus talks to.
    It has a number of modbus units (attribute 'units'.

    Do not instantiate directly; instead, use

        >>> host = client.host("foo.example")
    """

    _scope = None

    max_req_len = 50  # max number of registers to fetch w/ one request

    def __init__(self, gate, addr, port):
        self.gate = gate
        self.addr = addr
        self.port = port
        self.units = {}
        self.framer = ModbusSocketFramer(ClientDecoder())

        self._connect_lock = anyio.Lock()
        self._wqueue = Queue(100)
        self.stream = None
        self._transactions = {}
        self._tid = 0
        self._tg = None
        self._read_scope = None

        self.timeout = 10
        self._connected = anyio.Event()
        self._send_lock = anyio.Lock()

        gate._tg.start_soon(self._reader)

    def unit(self, unit):
        """
        Returns the `Unit` object registered to nr. @unit.

        A new unit is allocated if it doesn't yet exist.
        """
        try:
            return self.units[unit]
        except KeyError:
            if unit < 1 or unit > 247:
                raise ValueError(  # pylint: disable=raise-missing-from
                    f"Bus units must be in range 1…247, not {unit}"
                )
            return Unit(self, unit)

    def _add_unit(self, unit):
        self.units[unit.unit] = unit

    def _del_unit(self, unit):
        if self.units is None:
            return
        del self.units[unit.unit]

    # reader task #

    async def _reader(self):
        # pylint: disable=protected-access

        async def _send_trans(task_status):
            tr = list(self._transactions.values())
            task_status.started()
            try:
                for request in tr:
                    packet = self.framer.buildPacket(request)
                    async with self._send_lock:
                        await self.stream.send(packet)
            except Exception:  # pylint: disable=broad-except
                _logger.exception("Re-Write to %s:%d", self.addr, self.port)

        async with anyio.create_task_group() as self._tg:
            self._read_scope = self._tg.cancel_scope
            while True:
                if self.stream is None:
                    self.stream = await anyio.connect_tcp(self.addr, self.port)
                    # set so_linger to force sending RST instead of FIN
                    self.stream.extra(SocketAttribute.raw_socket).setsockopt(
                        socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                    )
                    # re-send open requests
                    await self._tg.start(_send_trans)
                    self._connected.set()

                try:
                    data = await self.stream.receive(4096)

                    if _logger.isEnabledFor(logging.DEBUG):
                        # pylint: disable=logging-not-lazy
                        _logger.debug("recv: " + " ".join([hex(x) for x in data]))

                    # unit = self.framer.decode_data(data).get("uid", 0)
                    replies = []

                    # check for decoding errors
                    self.framer.processIncomingPacket(
                        data, replies.append, unit=0, single=True
                    )  # bah

                except (
                    IncompleteRead,
                    ConnectionRefusedError,
                    ConnectionResetError,
                    ClosedResourceError,
                    ModbusIOException,
                    anyio.BrokenResourceError,
                ) as exc:
                    if self._connected.is_set():
                        self._connected = anyio.Event()
                    _logger.exception("Read from %s:%d", self.addr, self.port)

                    t, self._transactions = self._transactions, None
                    for req in t.values():
                        req._response_value.set(exc)

                    await self.disconnect()

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

    # main entry point #

    def _nextTID(self):
        self._tid = (self._tid + 1) % 0xFFFF
        return self._tid

    async def disconnect(self):
        """Close the TCP connection and set `self.stream = None`."""
        s, self.stream = self.stream, None
        if s:
            await s.close()

        # delay to give the device the chance to reinitialize
        await anyio.sleep(DISCONNECT_DELAY)

    async def execute(self, request):
        """
        Send a pymodbus request and wait for / return the reply.
        """
        # pylint: disable=logging-fstring-interpolation,protected-access

        request.transaction_id = self._nextTID()
        packet = self.framer.buildPacket(request)
        if _logger.isEnabledFor(logging.DEBUG):
            packet_info = " ".join([hex(x) for x in packet])
            _logger.debug(f"Gateway {self.addr}:{self.port} xmit: {packet_info}")

        # make the modbus request
        request._response_value = ValueEvent()

        await self._connected.wait()

        try:
            self._transactions[request.transaction_id] = request
            packet = self.framer.buildPacket(request)
            async with self._send_lock:
                await self.stream.send(packet)
            res = await request._response_value.get()
        except BaseException as exc:
            _logger.error(f"Gateway {self.addr}:{self.port} not replied: {repr(exc)}")

            raise
        else:
            if res.isError():
                raise ModbusError(res)

            if hasattr(res, "registers"):
                registers_info = " ".join([hex(x) for x in res.registers])
                _logger.debug(f"Gateway {self.addr}:{self.port} replied: {registers_info}")
            else:
                _logger.debug(f"Gateway {self.addr}:{self.port} replied: {res}")
            return res

        finally:
            self._transactions.pop(request.transaction_id, None)


class Unit:
    """This is a single modbus unit. It has any number of time slots
    (attribute 'slots'). Simply indexing a unit will return a timeslot
    object (existing or new). You can use anything hashable as the index.

    Units are always linked to a host. Use

        >>> unit = host.unit(1)

    to access/create a unit.
    """

    def __init__(self, host, unit):
        self.host = host
        self.unit = unit
        self.slots = {}

    def slot(self, slot):
        """
        Returns the `Slot` object registered to @slot.

        A new slot is allocated if it doesn't yet exist.
        """
        try:
            return self.slots[slot]
        except KeyError:
            s = Slot(self, slot)
            self.slots[slot] = s
            return s

    def _del_slot(self, slot):
        del self.slots[slot.slot]

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


class Slot:
    """This class represents a single "atomic" access to Modbus. The system
    will try to fetch all values in this slot, using as few+small requests
    as possible.

    Slots are always linked to a unit. Use

        >>> slot = unit.slot("20seconds")

    to access/create a slot.

    The intended usecase is that some values should be retrieved at
    different intervals than others. Thus the user creates several slots,
    adds the required fields to them, and then calls their `run` method
    when required.
    """

    _run_scope = None

    def __init__(self, unit, slot):
        self.unit = unit
        self.slot = slot
        self.modes = {}

    @property
    def is_empty(self):
        """
        Check whether the slot has no registered measurements.
        """
        for offsets in self.modes.values():
            if offsets.values:
                return False
        return True

    def add(self, typ: TypeCodec, offset: int, cls: Type[BaseValue]) -> BaseValue:
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
        val = cls() if isinstance(cls, type) else cls
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

    def __repr__(self):
        return f"<{self.__class__.__name__}>"

    async def _stop_run(self):
        if self._run_scope is not None:
            await self._run_scope.cancel()

    async def aclose(self):
        """
        Close this slot.
        """
        if self.unit is None:
            return
        m, self.modes = self.modes, None
        await self._stop_run()
        self.unit._del_slot(self)  # pylint: disable=protected-access
        self.unit = None

        for vl in m.values():
            vl.close()

    async def getValues(self) -> Dict[TypeCodec, Dict[int, Any]]:
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
                if self._run_scope is not None:
                    raise RuntimeError("already running")
                self._run_scope = tg.cancel_scope

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
            self._run_scope = None

    async def setValues(self):
        """
        Send a message writing the values in this block to the bus.
        """
        try:
            async with anyio.create_task_group() as tg:
                if self._run_scope is not None:
                    raise RuntimeError("already running")
                self._run_scope = tg.cancel_scope

                for vl in self.modes.values():
                    tg.start_soon(vl.writeValues)
            if self.unit is None:
                raise ClosedResourceError("dropped while running")
        finally:
            self._run_scope = None


class ValueList(DataBlock):
    """This class holds a list of to-be-accessed values.

    Do not instantiate directly; constructed and returned by

        >>> slot.add(InputRegisters, 2, IntValue)

    """

    def __init__(self, slot, kind):
        super().__init__(max_len=slot.unit.host.max_req_len)
        self.slot = slot
        self.kind = kind

    async def readValues(self, *, res=None):
        """
        Send messages reading these values to the bus.

        Returns a (offset,value) dict.
        """
        if res is None:
            res = {}
        async with anyio.create_task_group() as tg:
            for start, length in self.ranges():
                tg.start_soon(partial(self.readBlock, start, length, res=res))
        return res

    async def writeValues(self):
        """
        Send messages writing our values to the bus.
        """
        async with anyio.create_task_group() as tg:
            for start, length in self.ranges():
                tg.start_soon(partial(self.writeBlock, start, length))

    async def readBlock(self, start, length, *, res=None):
        """Send one message, decode the reply"""
        if res is None:
            res = {}
        u = self.slot.unit
        msg = self.kind.encoder(address=start, count=length, unit=u.unit)

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
            msg = self.kind.encoder_s(address=start, unit=u.unit, value=values[0])
        else:
            msg = self.kind.encoder_m(address=start, count=length, unit=u.unit, values=values)

        r = await u.host.execute(msg)  # pylint: disable=unused-variable
        # TODO check R for correct type?

    def close(self):
        """disable further accesses"""
        if self.slot is None:
            return
        self.slot = None
        self.values = None
