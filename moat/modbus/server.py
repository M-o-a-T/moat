#!/usr/bin/python3

"""
Modbus server classes for serial(RTU) and TCP.
"""

import logging
import socket
from binascii import b2a_hex
from contextlib import asynccontextmanager
from typing import Type, Union

import anyio
from anyio.abc import SocketAttribute
from moat.util import CtxObj
from pymodbus.constants import Defaults
from pymodbus.datastore import ModbusServerContext, ModbusSlaveContext
from pymodbus.device import ModbusControlBlock, ModbusDeviceIdentification
from pymodbus.exceptions import NoSuchSlaveException
from pymodbus.factory import ServerDecoder
from pymodbus.pdu import ModbusExceptions as merror
from pymodbus.utilities import hexlify_packets

from moat.modbus.types import BaseValue, DataBlock, TypeCodec

_logger = logging.getLogger(__name__)


class UnitContext(ModbusSlaveContext):
    """
    This module implements a slave context for servers that stores
    individual variables.
    """

    def __init__(self, server, unit):
        super().__init__(
            di=DataBlock(),
            co=DataBlock(),
            ir=DataBlock(),
            hr=DataBlock(),
            zero_mode=True,
        )
        self.unit = unit
        server._add_unit(self)

    def add(
        self, typ: TypeCodec, offset: int, val: Union[BaseValue, Type[BaseValue]]
    ) -> BaseValue:
        """Add a field to be served.

        :param typ: The `TypeCodec` instance to use.
        :param offset: The value's numeric offset, zero-based.
        :param val: The data type (baseValue instance)

        `cls` is either the decoder (subclass of `BaseValue`),
        or an existing `BaseValue` instance.
        """
        k = self.store[typ.key]
        if isinstance(val, type):
            val = val()
        k.add(offset, val)
        return val

    def remove(self, typ: TypeCodec, offset: int):
        """Remove a field to be requested.

        :param typ: the `TypeCodec` to use
        :param offset: the offset where the value is located

        Returns the field in question, or none if it doesn't exist.
        """
        k = self.store[typ.key]
        return k.delete(offset)


class BaseModbusServer(CtxObj):
    """Basic base class for servers."""

    def __init__(self, identity=None, response_manipulator=None):
        self.context = ModbusServerContext(single=False)
        self.context._slaves = self.units = {}
        self.control = ModbusControlBlock()
        self.broadcast_enable = False
        self.response_manipulator = response_manipulator

        if isinstance(identity, ModbusDeviceIdentification):
            self.control.Identity.update(identity)

        if identity is None:
            identity = ModbusDeviceIdentification()
            identity.VendorName = "Matthias Urlichs"
            identity.ProductCode = "MoaT.modbus"
            identity.VendorUrl = "http://M-o-a-T.org/"
            identity.ProductName = "MoaT-Modbus Test"
            identity.ModelName = "MoaT-Modbus Test"
            identity.MajorMinorRevision = "1.0"
        self.identity = identity

    def add_unit(self, unit) -> UnitContext:
        """
        Add an empty unit (= slave context) to this server (and return it).

        The unit must not exist.
        """
        if unit in self.units:
            raise RuntimeError(f"Unit {unit} already exists")
        return UnitContext(self, unit)

    def _add_unit(self, unit):
        self.units[unit.unit] = unit

    async def serve(self, opened=None):
        """The actual server. Override me."""
        raise RuntimeError("You need to override .serve")

    async def process_request(self, request):
        """Basic async request processor"""
        context = self.context[request.unit_id]
        response = request.execute(context)
        return response

    @asynccontextmanager
    async def _ctx(self):
        async with anyio.create_task_group() as tg:
            evt = anyio.Event()
            tg.start_soon(self.serve, evt)
            try:
                await evt.wait()
                yield self
            finally:
                tg.cancel_scope.cancel()


class SerialModbusServer(BaseModbusServer):
    """
    A simple serial Modbus server (RTU).
    """

    _serial = None
    framer = None
    ignore_missing_slaves = False

    def __init__(self, identity=None, **args):
        super().__init__(identity=identity)
        self.args = args

        from pymodbus.framer.rtu_framer import (  # pylint: disable=import-outside-toplevel
            ModbusRtuFramer,
        )

        self.decoder = ServerDecoder()  # pylint: disable=no-value-for-parameter ## duh?
        self.Framer = ModbusRtuFramer

    async def serve(self, opened=None):
        from anyio_serial import Serial  # pylint: disable=import-outside-toplevel

        async with Serial(**self.args) as ser:
            self._serial = ser
            self.framer = self.Framer(self.decoder)
            while True:
                data = await ser.read()
                msgs = []
                self.framer.processIncomingPacket(
                    data=data,
                    callback=msgs.append,
                    unit=self.units,
                    single=False,
                )
                for msg in msgs:
                    await self._process(msg)

    async def _process(self, request):
        broadcast = False

        try:
            if self.broadcast_enable and not request.unit_id:
                broadcast = True
                # if broadcasting then execute on all slave contexts,
                # note response will be ignored
                for unit_id in self.context.slaves():
                    response = await request.execute(self.context[unit_id])
            else:
                response = await self.process_request(request)
        except NoSuchSlaveException:
            txt = f"requested slave does not exist: {request.unit_id}"
            _logger.error(txt)
            if self.ignore_missing_slaves:
                return  # the client will simply timeout waiting for a response
            response = request.doException(merror.GatewayNoResponse)
        except Exception:  # pylint: disable=broad-except
            _logger.exception("Unable to fulfill request")
            response = request.doException(merror.SlaveFailure)
        # no response when broadcasting
        if request.should_respond and not broadcast:
            response.transaction_id = request.transaction_id
            response.unit_id = request.unit_id
            skip_encoding = False
            if self.response_manipulator:
                response, skip_encoding = self.response_manipulator(response)
            if not skip_encoding:
                response = self.framer.buildPacket(response)
            if _logger.isEnabledFor(logging.DEBUG):
                _logger.debug("send: [%s]- %s", request, b2a_hex(response))

            await self._serial.send(response)


class ModbusServer(BaseModbusServer):
    """TCP Modbus server.

    If the identity structure is not passed in, the ModbusControlBlock
    uses its own empty structure.

    :param identity: An optional identity structure
    :param address: An optional address to bind to.
    :param port: the TCP port to listen on.
    """

    taskgroup = None

    def __init__(self, identity=None, address=None, port=None):
        super().__init__(identity=identity)

        from pymodbus.framer.socket_framer import (  # pylint: disable=import-outside-toplevel
            ModbusSocketFramer,
        )

        self.decoder = ServerDecoder()
        self.framer = ModbusSocketFramer
        self.address = address or "localhost"
        self.port = port if port is not None else Defaults.Port

    async def serve(self, opened=None):
        """Run this server.
        Sets the `opened` event, if given, as soon as the server port is open.
        """
        try:
            async with anyio.create_task_group() as tg:
                self.taskgroup = tg
                async with await anyio.create_tcp_listener(
                    local_port=self.port,
                    local_host=self.address,
                    reuse_port=True,
                ) as server:
                    if self.port == 0:
                        self.port = server.listeners[0].extra_attributes[
                            SocketAttribute.local_address
                        ]()[1]
                    if opened is not None:
                        opened.set()

                    await server.serve(self._serve_one)
        except socket.gaierror:
            _logger.error("Trying to look up %s", self.address)
            raise
        finally:
            self.taskgroup = None

    async def _serve_one(self, conn):
        reset_frame = False
        framer = self.framer(decoder=self.decoder)

        while True:
            try:
                data = await conn.receive(4096)
                if data == b"":
                    break
                if _logger.isEnabledFor(logging.DEBUG):
                    _logger.debug(  # pylint: disable=logging-not-lazy
                        "Handling data: " + hexlify_packets(data)
                    )

                reqs = []
                # TODO fix pymodbus
                framer.processIncomingPacket(
                    data, reqs.append, list(self.units.keys()), single=False
                )

                for request in reqs:
                    try:
                        response = await self.process_request(request)
                    except NoSuchSlaveException:
                        _logger.debug("requested slave does not exist: %d", request.unit_id)
                        response = request.doException(merror.GatewayNoResponse)
                    except Exception as exc:  # pylint: disable=broad-except
                        _logger.warning("Datastore unable to fulfill request", exc_info=exc)
                        response = request.doException(merror.SlaveFailure)
                    if response.should_respond:
                        response.transaction_id = request.transaction_id
                        response.unit_id = request.unit_id
                        # self.server.control.Counter.BusMessage += 1
                        pdu = framer.buildPacket(response)
                        if _logger.isEnabledFor(logging.DEBUG):
                            _logger.debug("send: %s", b2a_hex(pdu))
                        await conn.send(pdu)

            except socket.timeout as msg:
                _logger.debug("Socket timeout occurred: %r", msg)
                reset_frame = True
            except socket.error as msg:
                _logger.error("Socket error occurred: %r", msg)
                return
            except anyio.get_cancelled_exc_class():
                raise
            except anyio.BrokenResourceError:
                return
            except Exception:  # pylint: disable=broad-except
                _logger.exception("Server error")
                return
            finally:
                if reset_frame:
                    framer.resetFrame()
                    reset_frame = False


class MockAioModbusServer(ModbusServer):
    """A test modbus server with static data"""

    pass  # pylint: disable=unnecessary-pass


class ForwardingAioModbusServer:
    """A modbus server mix-in that forwards requests to a modbus client"""

    def __init__(self):
        self._units = {}

    def add_unit(self, unit):  # pylint: disable=missing-function-docstring
        raise RuntimeError("Use 'set_forward' with a forwarding server")

    def set_forward(
        self, id, unit: ModbusSlaveContext = None
    ):  # pylint: disable=redefined-builtin
        """Arrange for requests to the given ID to be forwarded
        to this client.

        Use unit=None to stop forwarding.
        """
        if unit is None:
            del self._units[id]
        else:
            self._units[id] = unit

    async def process_request(self, request):
        """Process this request by forwarding it to the client."""
        old_unit = request.unit_id
        old_tid = request.transaction_id

        unit = self._units[request.unit_id]
        request.unit_id = unit.unit
        try:
            async with unit.concurrent_requests:
                return await unit.host.execute(request)
        finally:
            request.unit_id = old_unit
            request.transaction_id = old_tid
