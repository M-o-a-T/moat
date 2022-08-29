#!/usr/bin/python3

import anyio
import socket
from collections.abc import Mapping, Iterable

from pymodbus.constants import Defaults
from pymodbus.datastore import ModbusSlaveContext, ModbusServerContext
from pymodbus.datastore.store import BaseModbusDataBlock
from pymodbus.device import ModbusControlBlock
from pymodbus.device import ModbusDeviceIdentification
from pymodbus.exceptions import NoSuchSlaveException
from pymodbus.factory import ServerDecoder
from pymodbus.framer.socket_framer import ModbusSocketFramer
from pymodbus.pdu import ModbusExceptions as merror
from pymodbus.utilities import hexlify_packets

from binascii import b2a_hex
import traceback

import logging

_logger = logging.getLogger(__name__)


class DataBlock(dict, BaseModbusDataBlock):
    """Your basic sparse data block"""

    def __init__(self):
        pass

    def default(self, count, value=False):
        raise NotImplementedError

    def reset(self):
        raise NotImplementedError

    def validate(self, address, count=1):
        if not count:
            return False
        while count:
            if address not in self:
                return False
            address += 1
            count -= 1
        return True

    def getValues(self, address, count=1):
        return [self[i] for i in range(address, address + count)]

    def setValues(self, address, values):
        if isinstance(values, Mapping):
            for idx, val in values.items():
                self[idx] = val
        else:
            if not isinstance(values, Iterable):
                values = [values]
            for idx, val in enumerate(values):
                self[address + idx] = val

    def deleteValues(self, address, count=1):
        while count:
            self.pop(address, None)
            address += 1
            count -= 1


class BaseAioModbusServer:
    def __init__(self, identity=None, address=None, port=None):
        """Initializer for the Modbus server.

        If the identify structure is not passed in, the ModbusControlBlock
        uses its own empty structure.

        :param identity: An optional identify structure
        :param address: An optional address to bind to.
        :param port: the TCP port to listen on.
        """
        self.decoder = ServerDecoder()
        self.framer = ModbusSocketFramer
        self.context = ModbusServerContext(single=False)
        self.context._slaves = self.slaves = {}
        self.control = ModbusControlBlock()
        self.address = address or "localhost"
        self.port = port if port is not None else Defaults.Port

        if isinstance(identity, ModbusDeviceIdentification):
            self.control.Identity.update(identity)

        if identity is None:
            identity = ModbusDeviceIdentification()
            identity.VendorName = "noris network AG"
            identity.ProductCode = "CG"
            identity.VendorUrl = "http://gitlab.noris.net/ColGate/ColGate/"
            identity.ProductName = "ColGate Test"
            identity.ModelName = "ColGate Test"
            identity.MajorMinorRevision = "1.0"
        self.identity = identity

    def add_slave(self, unit):
        raise RuntimeError("You need to override .add_slave")

    async def serve(self, opened=None):
        """Run this server.
        Sets the `opened` event, if given, as soon as the server port is open.
        """
        try:
            async with anyio.create_task_group() as tg:
                self.taskgroup = tg
                async with await anyio.create_tcp_server(
                    port=self.port, interface=self.address
                ) as server:
                    if self.port == 0:
                        self.port = server.port
                    if opened is not None:
                        await opened.set()
                    async for conn in server.accept_connections():
                        await tg.spawn(self._serve_one, conn)
        except socket.gaierror as exc:
            _logger.error(f"Trying to look up {self.address}")
        finally:
            self.taskgroup = None

    async def process_request(self, request):
        raise RuntimeError("You need to override .process_request")

    async def _serve_one(self, conn):
        reset_frame = False
        framer = self.framer(decoder=self.decoder)

        while True:
            try:
                data = await conn.receive_some(4096)
                if data == b"":
                    break
                _logger.debug("Handling data: " + hexlify_packets(data))

                reqs = []

                def unbox(req):
                    reqs.append(req)

                framer.processIncomingPacket(data, unbox, (), single=True)

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
                        await conn.send_all(pdu)

            except socket.timeout as msg:
                _logger.debug(f"Socket timeout occurred {msg}")
                reset_frame = True
            except socket.error as msg:
                _logger.error(f"Socket error occurred {msg}")
                self.running = False
            except anyio.get_cancelled_exc_class():
                raise
            except Exception as exc:
                _logger.error(f"Socket exception occurred {traceback.format_exc()}")
                self.running = False
                reset_frame = True
            finally:
                if reset_frame:
                    framer.resetFrame()
                    reset_frame = False


class MockAioModbusServer(BaseAioModbusServer):
    """A test modbus server with static data"""

    async def process_request(self, request):
        context = self.context[request.unit_id]
        response = request.execute(context)
        return response

    def add_slave(self, unit):
        try:
            return self.slaves[unit]
        except KeyError:
            self.slaves[unit] = s = ModbusSlaveContext(
                di=DataBlock(),
                co=DataBlock(),
                hr=DataBlock(),
                ir=DataBlock(),
                zero_mode=True,
            )
            return s


class ForwardingAioModbusServer(BaseAioModbusServer):
    """A modbus server that forwards requests to a modbus client"""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.units = {}

    def set_forward(self, id, unit=None):
        """Arrange for requests to the given ID to be forwarded
        to this client.

        Set the unit to None to stop forwarding.
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
