#!/usr/bin/python3

import anyio
import socket
from collections.abc import Mapping, Iterable
from typing import Dict

from pymodbus.constants import Defaults
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore.store import BaseModbusDataBlock
from pymodbus.device import ModbusControlBlock
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.exceptions import NoSuchSlaveException
from pymodbus.factory import ServerDecoder
from pymodbus.pdu import ModbusExceptions as merror
from pymodbus.utilities import hexlify_packets

from asyncmodbus.types import DataBlock

from binascii import b2a_hex
import traceback

import logging

_logger = logging.getLogger(__name__)


class BaseModbusServer:
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
            identity.ProductName = "AsyncModbus Test"
            identity.ModelName = "AsyncModbus Test"
            identity.MajorMinorRevision = "1.0"
        self.identity = identity

    def add_unit(self, unit):
        if unit in self.units:
            raise RuntimeError(f"Unit {unit} already exists")
        self.units[unit] = s = ModbusSlaveContext(
            di = DataBlock(),
            co = DataBlock(),
            ir = DataBlock(),
            hr = DataBlock(),
            zero_mode=True,
        )
        return s

    async def serve(self, opened=None):
        raise RuntimeError("You need to override .serve")

    async def process_request(self, request):
        context = self.context[request.unit_id]
        response = request.execute(context)
        return response



class SerialModbusServer(BaseModbusServer):
    def __init__(self, identity=None, **args):
        super().__init__(identity=identity)
        self.args = args

        from pymodbus.framer.rtu_framer import ModbusRtuFramer

        self.decoder = ServerDecoder()
        self.framer = ModbusRtuFramer

    async def serve(self, opened=None):
        from anyio_serial import Serial

        self._serial = ser = serial.open(**args)
        while True:
            data = await ser.read()
            msgs = []
            self.framer.processIncomingPacket(
                data=data,
                callback=lambda x: append(msgs, x),
                unit=self.units,
                single=False,
            )
            for msg in msgs:
                await self._process(msg)

    async def _process(self, msg):
        broadcast = False

        try:
            if self.broadcast_enable and not request.unit_id:
                broadcast = True
                # if broadcasting then execute on all slave contexts,
                # note response will be ignored
                for unit_id in self.context.slaves():
                    response = request.execute(self.context[unit_id])
            else:
                context = self.context[request.unit_id]
                response = request.execute(context)
        except NoSuchSlaveException:
            txt = f"requested slave does not exist: {request.unit_id}"
            _logger.error(txt)
            if self.ignore_missing_slaves:
                return  # the client will simply timeout waiting for a response
            response = request.doException(merror.GatewayNoResponse)
        except Exception as exc:  # pylint: disable=broad-except
            txt = (
                f"Datastore unable to fulfill request: {exc}; {traceback.format_exc()}"
            )
            _logger.error(txt)
            response = request.doException(merror.SlaveFailure)
        # no response when broadcasting
        if message.should_respond and not broadcast:
            response.transaction_id = request.transaction_id
            response.unit_id = request.unit_id
            skip_encoding = False
            if self.response_manipulator:
                response, skip_encoding = self.response_manipulator(response)
            self.send(response, *addr, skip_encoding=skip_encoding)


class ModbusServer(BaseModbusServer):
    def __init__(self, identity=None, address=None, port=None):
        """Initializer for the Modbus server.

        If the identify structure is not passed in, the ModbusControlBlock
        uses its own empty structure.

        :param identity: An optional identify structure
        :param address: An optional address to bind to.
        :param port: the TCP port to listen on.
        """
        super().__init__(identity=identity)

        from pymodbus.framer.socket_framer import ModbusSocketFramer

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
                    local_port=self.port, local_host=self.address,
                    reuse_port=True,
                ) as server:
                    if self.port == 0:
                        self.port = server.port
                    if opened is not None:
                        await opened.set()

                    await server.serve(self._serve_one)
        except socket.gaierror as exc:
            _logger.error(f"Trying to look up {self.address}")
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
                _logger.debug("Handling data: " + hexlify_packets(data))

                reqs = []
                # TODO fix pymodbus
                framer.processIncomingPacket(data, lambda req: reqs.append(req), list(self.units.keys()), single=False)

                for request in reqs:
                    try:
                        response = await self.process_request(request)
                    except NoSuchSlaveException as ex:
                        _logger.debug(
                            f"requested slave does not exist: {request.unit_id}"
                        )
                        response = request.doException(merror.GatewayNoResponse)
                    except Exception as ex:
                        _logger.debug(
                            f"Datastore unable to fulfill request: {ex}; {traceback.format_exc()}"
                        )
                        response = request.doException(merror.SlaveFailure)
                    if response.should_respond:
                        response.transaction_id = request.transaction_id
                        response.unit_id = request.unit_id
                        # self.server.control.Counter.BusMessage += 1
                        pdu = framer.buildPacket(response)
                        _logger.debug(f"send: {b2a_hex(pdu)}")
                        await conn.send(pdu)

            except socket.timeout as msg:
                _logger.debug(f"Socket timeout occurred {msg}")
                reset_frame = True
            except socket.error as msg:
                _logger.error(f"Socket error occurred {msg}")
                return
            except anyio.get_cancelled_exc_class():
                raise
            except anyio.BrokenResourceError:
                return
            except Exception as exc:
                _logger.error(f"Socket exception occurred {traceback.format_exc()}")
                return
            finally:
                if reset_frame:
                    framer.resetFrame()
                    reset_frame = False


class MockAioModbusServer(ModbusServer):
    """A test modbus server with static data"""
    pass


class ForwardingAioModbusServer:
    """A modbus server mix-in that forwards requests to a modbus client"""

    def add_unit(self, unit):
        raise RuntimeError("Use 'set_forward' with a forwarding server")

    def set_forward(self, id, unit:ModbusSlaveContext = None):
        """Arrange for requests to the given ID to be forwarded
        to this client.

        Use unit=None to stop forwarding.
        """
        if unit is None:
            del self.units[id]
        else:
            self.units[id] = unit

    async def process_request(self, request):
        """Process this request by forwarding it to the client."""
        old_unit = request.unit_id
        old_tid = request.transaction_id

        unit = self.units[request.unit_id]
        request.unit_id = unit.unit
        try:
            async with unit.concurrent_requests:
                return await unit.host.execute(request)
        finally:
            request.unit_id = old_unit
            request.transaction_id = old_tid
