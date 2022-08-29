"""
modbus access
"""
import anyio
import socket
import struct
from anyio.exceptions import IncompleteRead, ClosedResourceError
from async_generator import async_generator, yield_, asynccontextmanager
from contextlib import suppress
from functools import partial

from pymodbus.compat import byte2int
from pymodbus.exceptions import ModbusIOException
from pymodbus.factory import ClientDecoder
from pymodbus.transaction import ModbusSocketFramer
from pymodbus.client.common import (
    ReadDiscreteInputsRequest,
    ReadDiscreteInputsResponse,
    ReadCoilsRequest,
    ReadCoilsResponse,
    ReadHoldingRegistersRequest,
    ReadHoldingRegistersResponse,
    ReadInputRegistersRequest,
    ReadInputRegistersResponse,
)

from ..config.prometheus_metrics import increment_shared_metric
from .util import ValueEvent

import logging

_logger = logging.getLogger(__name__)

__all__ = [
    "ColGate",
    "new_colgate",
    "ModbusError",
    "Coils",
    "DiscreteInputs",
    "HoldingRegisters",
    "InputRegisters",
    "InaccessibleValue",
    "IntValue",
    "LongValue",
    "SwappedLongValue",
    "SignedIntValue",
    "SignedLongValue",
    "SwappedSignedLongValue",
    "SignedSwappedLongValue",
    "FloatValue",
    "SwappedFloatValue",
    "DoubleValue",
    "SwappedDoubleValue",
    "QuadValue",
    "SwappedQuadValue",
    "SignedQuadValue",
    "SwappedSignedQuadValue",
]

# seconds to wait when disconnecting/reconnecting TCP for different unitID
DISCONNECT_DELAY = 0.1
RECONNECT_TIMEOUT = 10
CHECK_STREAM_TIMEOUT = 0.001


class ColGate:
    """The main Gate object. Do not instantiate directly; use
    `async with new_colgate() as gate:`.
    """

    def __init__(self, tg):
        self.taskgroup = tg
        self.hosts = {}

    def get_host(self, addr, port=502):
        """Return a host object for to this address+port.
        The host will be created if it has not been seen before.
        """
        try:
            return self.hosts[(addr, port)]
        except KeyError:
            host = Host(self, addr, port)
            self.hosts[(addr, port)] = host
            return host

    def _del_host(self, host):
        if self.hosts is None:
            return
        del self.hosts[(host.addr, host.port)]

    async def aclose(self):
        """Close and remove all hosts.
        """
        if self.hosts is None:
            return
        h, self.hosts = self.hosts, None
        async with anyio.open_cancel_scope(shield=True):
            for host in h.values():
                await host.aclose()
        await self.taskgroup.cancel_scope.cancel()


@asynccontextmanager
@async_generator
async def new_colgate():
    """Create a new ColGate client.

    Usage:

        >>> async with new_colgate() as gate:
        ...     host = gate.add_host("foo.example")
        ...     pass  # etc.
    """
    async with anyio.create_task_group() as tg:
        gate = ColGate(tg)
        try:
            await yield_(gate)
        finally:
            async with anyio.open_cancel_scope(shield=True):
                await tg.cancel_scope.cancel()
                await gate.aclose()


class ModbusError(RuntimeError):
    """Error entry in returned datasets"""

    def __init__(self, result):
        self.result = result


class Host:
    """This is a single host which ColGate talks to.
    It has a number of modbus units (attribute 'units'.
    Simply indexing a host will return a unit object
    (existing or new); use the unit number as index.

    Do not instantiate directly; instead, use

        >>> host = gate["foo.example"]
    """

    def __init__(self, gate, addr, port):
        self.gate = gate
        self.addr = addr
        self.port = port
        self.units = {}
        self.framer = ModbusSocketFramer(ClientDecoder())

        self._connect_lock = anyio.create_lock()
        self._wqueue = anyio.create_queue(100)
        self.stream = None
        self.transactions = {}
        self._tid = 0
        self._read_scope = None
        self._write_scope = None

        self.timeout = 10

    def __getitem__(self, unit):
        try:
            return self.units[unit]
        except KeyError:
            if unit < 1 or unit > 255:
                raise ValueError(f"Bus units must be in range 1…255, not {unit}")
            u = Unit(self, unit)
            self.units[unit] = u
            return u

    def _del_unit(self, unit):
        if self.units is None:
            return
        del self.units[unit.unit]

    # read/write tasks #

    async def _reader(self, val, transaction_id):
        async with anyio.open_cancel_scope() as scope:
            await val.set(scope)
            try:
                async with anyio.fail_after(self.timeout):
                    data = await self.stream.receive_some(4096)
                if data == b"":
                    raise ClosedResourceError
            except (
                StopAsyncIteration,
                TimeoutError,
                IncompleteRead,
                ConnectionRefusedError,
                ConnectionResetError,
                ClosedResourceError,
            ) as exc:
                # add error message and set the value of request to the exception object
                request = self.transactions.pop(transaction_id)
                exc.message = "Modbus read error response in _reader"
                await request.__value.set(exc)

                # disconnect in case of any error
                await self.disconnect()

            else:
                _logger.debug("recv: " + " ".join([hex(byte2int(x)) for x in data]))
                # unit = self.framer.decode_data(data).get("uid", 0)
                replies = []

                def addReply(r):
                    if r is not None:
                        replies.append(r)

                # check for decoding errors
                try:
                    self.framer.processIncomingPacket(
                        data, addReply, unit=0, single=True
                    )  # bah
                except ModbusIOException as exc:
                    request = self.transactions.pop(transaction_id)
                    exc.message = "Error in IncomingPacket's decoding"
                    await request.__value.set(exc)

                    await self.disconnect()

                for reply in replies:
                    tid = reply.transaction_id
                    try:
                        request = self.transactions.pop(tid)
                    except KeyError:
                        _logger.info(f"Unrequested message: {reply}")
                    else:
                        await request.__value.set(reply)

    async def start(self):
        """Start talking to this host. Returns when the connection is
        established, raises an error if not possible.

        TODO: if the connection subsequently drops, it's re-established
        transparently.

        This is called automatically as soon as the first request is
        started.
        """
        if self._write_scope is not None:
            return

        v_w = ValueEvent()
        await self.gate.taskgroup.spawn(self._writer, v_w)
        self._write_scope = await v_w.get()

    async def _writer(self, val):
        async with anyio.open_cancel_scope() as scope:
            await val.set(scope)
            while True:
                request = await self._wqueue.get()
                packet = self.framer.buildPacket(request)
                self.transactions[request.transaction_id] = request

                # check if stream was closed by remote host
                if self.stream:
                    try:
                        # stream is working if TimeoutError is raised
                        with suppress(TimeoutError):
                            async with anyio.fail_after(CHECK_STREAM_TIMEOUT):
                                data = await self.stream.receive_some(4096)
                                if data == b"":
                                    raise ClosedResourceError
                    except Exception as exc:
                        await self.stream.close()  # trigger reconnecting if stream was closed by remote host
                        self.stream = None
                        _logger.debug(
                            f"{repr(exc)}: Stream was closed by remote host {self.addr}:{self.port}"
                        )

                try:
                    if self.stream == None:
                        self.stream = await anyio.connect_tcp(self.addr, self.port)
                        # set so_linger to force sending RST instead of FIN
                        self.stream.setsockopt(
                            socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0)
                        )

                    await self.stream.send_all(packet)

                except OSError as exc:
                    # add error message and set the value of request to the exception object
                    request = self.transactions.pop(request.transaction_id)
                    exc.message = "TCP error in _writer"
                    await request.__value.set(exc)

                    # disconnect in case of error
                    await self.disconnect()

                else:
                    # start _reader task
                    v_r = ValueEvent()
                    await self.gate.taskgroup.spawn(
                        self._reader, v_r, request.transaction_id
                    )
                    self._read_scope = await v_r.get()

    async def aclose(self):
        """Stop talking and remove from ColGate.

        This is a coroutine.
        """
        if self.gate is None:
            return
        u, self.units = self.units, None
        for unit in u.values():
            await unit.aclose()

        self.gate._del_host(self)
        self.gate = None

        if self.stream is None:
            return

        if self._write_scope is not None:
            await self._write_scope.cancel()
            self._write_scope = None
        if self._read_scope is not None:
            await self._read_scope.cancel()
            self._read_scope = None

        try:
            await self.stream.close()
        finally:
            self.stream = None

    # main entry point #

    def _nextTID(self):
        self._tid = (self._tid + 1) % 0xFFFF
        return self._tid

    async def disconnect(self):
        """Close the TCP connection and set `self.stream = None`."""
        if self._write_scope:
            await self._write_scope.cancel()
            self._write_scope = None
        if self._read_scope:
            await self._read_scope.cancel()
            self._read_scope = None
        if self.stream:
            await self.stream.close()
            self.stream = None

        # delay to give the device the chance to reinitialize
        await anyio.sleep(DISCONNECT_DELAY)

    async def execute(self, request, **kwargs):
        """
        Send a pymodbus request and wait for / return the reply.
        """
        request.transaction_id = self._nextTID()
        packet = self.framer.buildPacket(request)
        if _logger.isEnabledFor(logging.DEBUG):
            packet_info = " ".join([hex(byte2int(x)) for x in packet])
            _logger.debug(f"Gateway {self.addr}:{self.port} received: {packet_info}")

        async with self._connect_lock:
            await self.start()  # will create the tasks or return immediately if already created

            # make the modbus request
            request.__value = ValueEvent()
            await self._wqueue.put(request)
            increment_shared_metric("modbus_requests")

            try:
                res = await request.__value.get()
            except BaseException as exc:
                _logger.error(
                    f"Gateway {self.addr}:{self.port} not replied: {repr(exc)}"
                )
                increment_shared_metric("modbus_failed_responses")
                raise
            if hasattr(res, "registers"):
                registers_info = " ".join([hex(byte2int(x)) for x in res.registers])
                _logger.debug(
                    f"Gateway {self.addr}:{self.port} replied: {registers_info}"
                )
            else:
                _logger.debug(f"Gateway {self.addr}:{self.port} replied: {res}")

            return res


class Unit:
    """This is a single modbus unit. It has any number of time slots
    (attribute 'slots'). Simply indexing a unit will return a timeslot
    object (existing or new). You can use any hashable as index.
    """

    def __init__(self, host, unit):
        self.host = host
        self.unit = unit
        self.slots = {}

    def __getitem__(self, slot):
        try:
            return self.slots[slot]
        except KeyError:
            s = Slot(self, slot)
            self.slots[slot] = s
            return s

    def _del_slot(self, slot):
        if self.slots is None:
            return
        del self.slots[slot.slot]

    async def aclose(self):
        """Stop talking and delete yourself.

        This is a coroutine.
        """
        if self.host is None:
            return
        self.host._del_unit(self)
        self.host = None

        s, self.slots = self.slots, None
        for slot in s.values():
            await slot.aclose()


class Slot:
    """This is a single "atomic" access to Modbus. ColGate will try to
    fetch the values in this slot using as few+small requests as possible.

    Add values to this slot with `register`. Execute the slot with `run`.

    Do not instantiate this class direct,y; instead, use

    >>> slot = unit["20seconds"]
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

    def add(self, typ, offset, val):
        """Add a field to be requested.

        :param typ: The TypeCodec instance to use.
        :param offset: The value's numeric offset
        :param val: The data type (baseValue instance)
        `val` is the decoder (subclass of `BaseValue`).
        """
        try:
            k = self.modes[typ]
        except KeyError:
            self.modes[typ] = k = ValueList(self, typ)
        return k.add(offset, val)

    def delete(self, typ, offset):
        """Delete a field to be requested.

        :param typ: the `TypeCodec` to use
        :param offset: the offset where the value has been added
        """
        try:
            k = self.modes[typ]
        except KeyError:
            return
        return k.delete(offset)

    def __repr__(self):
        return f"<self.__class__.__name__>"

    async def _stop_run(self):
        if self._run_scope is not None:
            await self._run_scope.cancel()

    async def aclose(self):
        """
        Close this slot.

        This is a coroutine.
        """
        if self.unit is None:
            return
        m, self.modes = self.modes, None
        await self._stop_run()
        self.unit._del_slot(self)
        self.unit = None

        for vl in m.values():
            vl.close()

    async def run(self):
        """
        Send a message reading these values to the bus.
        Returns a (type,(offset,value)) dict-of-dicts.
        On error, stores the error object instead of a dict.

        This code may return a partial result.
        """
        try:
            res = {}
            async with anyio.create_task_group() as tg:
                if self._run_scope is not None:
                    raise RuntimeError("already running")
                self._run_scope = tg.cancel_scope

                for typ, vl in self.modes.items():
                    res[typ] = r = {}
                    try:
                        await tg.spawn(partial(vl.run, res=r))
                    except ModbusError as r:
                        res[typ] = r.result
            if self.unit is None:
                raise ClosedResourceError("dropped while running")
            return res
        finally:
            self._run_scope = None


class ValueList:
    """This class holds a list of to-be-accessed values.

    Do not instantiate directly; used implicitly by

    >>> slot.add(InputRegisters, 2, IntValue)
    """

    def __init__(self, slot, kind):
        self.slot = slot
        self.kind = kind
        self.values = {}

    def add(self, offset, val):
        for i in range(offset, offset + val.len):
            if i in self.values:
                raise ValueError("Already known", i)
        self.values[offset] = val

    def delete(self, offset):
        self.values.pop(offset, None)

    def ranges(self):
        """Iterate over the to-be-retrieved range(s)."""
        start, cur = None, None
        for offset, val in sorted(self.values.items()):
            if isinstance(val, InaccessibleValue):
                if start is not None:
                    yield (start, cur - start)
                    start = None
            elif start is None:
                start = offset
                cur = start + val.len
            elif cur == offset and (cur + val.len - start) <= 125:
                cur += val.len
            else:
                yield (start, cur - start)
                start = offset
                cur = start + val.len
            # TODO cache the result
            # TODO reduce code duplication
            # TODO split when a length is >120
            # TODO don't open a new range when there's a gap (and enough space)
        if cur is not None:
            yield (start, cur - start)

    async def run(self, *, res=None):
        """
        Send messages reading these values to the bus.

        Returns a (type,(offset,value)) dict-of-dicts.
        """
        if res is None:
            res = {}
        async with anyio.create_task_group() as tg:
            for start, length in self.ranges():
                await tg.spawn(partial(self.run_one, start, length, res=res))
        return res

    async def run_one(self, start, length, *, res=None):
        """Send one message, decode the reply"""
        if res is None:
            res = {}
        u = self.slot.unit
        msg = self.kind.coder(address=start, count=length, unit=u.unit)

        # handle according to reply type
        r = await u.host.execute(msg)
        if isinstance(r, Exception):
            raise r
        elif r.isError():
            raise ModbusError(r)

        r = r.registers
        while r:
            try:
                val = self.values[start]
            except KeyError:
                off = 1
            else:
                off = val.len
                res[start] = val(r[:off])
            start += off
            r = r[off:]

    def close(self):
        if self.slot is None:
            return
        self.slot = None
        self.values = None


def singleton(x):
    x = x()
    return x


class BaseValue:
    """Base class for reading a single value.

    Do not instantiate.
    """

    len = 0

    def __call__(self):
        raise RuntimeError("This value doesn't.")


class InaccessibleValue(BaseValue):  # duck-types but does NOT interit BaseValue
    """This register range must not be accessed.

    Use an instance of this type (with appropriate length)
    to force splitting a request into multiple parts.

    :param len: The length of the block that may not be accessed.
    """

    def __init__(self, len):
        self.len = len


@singleton
class IntValue(BaseValue):
    """Simplest-possible value, one register.

    This is a BaseValue instance.
    """

    len = 1

    def __call__(self, regs):
        return regs[0]


@singleton
class LongValue(BaseValue):
    """32-bit integer, two registers, standard (big-endian) word order.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        return regs[0] * 65536 + regs[1]


@singleton
class SwappedLongValue(BaseValue):
    """32-bit integer, two registers, little-endian word order.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        return regs[1] * 65536 + regs[0]


@singleton
class QuadValue(BaseValue):
    """64-bit integer, four registers, standard (big-endian) word order.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        return ((regs[0] * 65536 + regs[1]) * 65536 + regs[2]) * 65536 + regs[3]


@singleton
class SwappedQuadValue(BaseValue):
    """64-bit integer, four registers, little-endian word order.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        return ((regs[3] * 65536 + regs[2]) * 65536 + regs[1]) * 65536 + regs[0]


@singleton
class SignedIntValue(BaseValue):
    """one register, signed.

    This is a BaseValue instance.
    """

    len = 1

    def __call__(self, regs):
        res = regs[0]
        if res >= 1 << 15:
            res -= 1 << 16
        return res


@singleton
class SignedLongValue(BaseValue):
    """two registers, signed.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        res = regs[0] * 65536 + regs[1]
        if res >= 1 << 31:
            res -= 1 << 32
        return res


@singleton
class SwappedSignedLongValue(BaseValue):
    """two registers, signed, swapped.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        res = regs[1] * 65536 + regs[0]
        if res >= 1 << 31:
            res -= 1 << 32
        return res


SignedSwappedLongValue = SwappedSignedLongValue


@singleton
class SignedQuadValue(BaseValue):
    """four registers, signed.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        res = ((regs[0] * 65536 + regs[1]) * 65536 + regs[2]) * 65536 + regs[3]
        if res >= 1 << 63:
            res -= 1 << 64
        return res


@singleton
class SwappedSignedQuadValue(BaseValue):
    """four registers, signed, swapped.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        res = ((regs[3] * 65536 + regs[2]) * 65536 + regs[1]) * 65536 + regs[0]
        if res >= 1 << 63:
            res -= 1 << 64
        return res


SignedSwappedQuadValue = SwappedSignedQuadValue


@singleton
class FloatValue(BaseValue):
    """network-ordered floating point.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        return struct.unpack(">f", struct.pack(">2H", *regs))


@singleton
class SwappedFloatValue(BaseValue):
    """network-ordered floating point.

    This is a BaseValue instance.
    """

    len = 2

    def __call__(self, regs):
        return struct.unpack(">f", struct.pack(">2H", regs[1], regs[0]))


@singleton
class DoubleValue(BaseValue):
    """network-ordered accurate floating point.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        return struct.unpack(
            ">d", struct.pack(">4H", regs[0], regs[1], regs[2], regs[3])
        )


@singleton
class SwappedDoubleValue(BaseValue):
    """network-ordered accurate floating point.

    This is a BaseValue instance.
    """

    len = 4

    def __call__(self, regs):
        return struct.unpack(
            ">d", struct.pack(">4H", regs[3], regs[2], regs[1], regs[0])
        )


class TypeCodec:
    """Base class for access types. Do not instantiate."""

    typ = None
    acc = None

    def __repr__(self):
        return self.__class__.__name__

    def __eq__(self, typ):
        if isinstance(typ, TypeCodec):
            typ = typ.typ
        return self.typ == typ

    def __hash__(self):
        return self.typ


@singleton
class Coils(TypeCodec):
    """Modbus 'coils' data.
    This is a TypeCodec.
    """

    typ = 0
    coder = ReadCoilsRequest
    decoder = ReadCoilsResponse


@singleton
class DiscreteInputs(TypeCodec):
    """Modbus 'discrete input' data.
    This is a TypeCodec.
    """

    typ = 1
    coder = ReadDiscreteInputsRequest
    decoder = ReadDiscreteInputsResponse


@singleton
class HoldingRegisters(TypeCodec):
    """Modbus 'holding register' data.
    This is a TypeCodec.
    """

    typ = 2
    coder = ReadHoldingRegistersRequest
    decoder = ReadHoldingRegistersResponse


@singleton
class InputRegisters(TypeCodec):
    """Modbus 'input register' data.
    This is a TypeCodec.
    """

    typ = 3
    coder = ReadInputRegistersRequest
    decoder = ReadInputRegistersResponse
