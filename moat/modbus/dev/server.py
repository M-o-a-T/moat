"""
implement a Modbus server.

Its job is to forward requests to clients, multiplexing the Modbus
connection to them, because some of these things are stupid and
only support one concurrent TCP connection.

"""

from __future__ import annotations

import logging

import anyio
from pymodbus.exceptions import ModbusIOException
from pymodbus.factory import ServerDecoder
from pymodbus.pdu import ExceptionResponse
from pymodbus.transaction import ModbusSocketFramer

logger = logging.getLogger(__name__)

__all__ = ["Server"]


class Forwarder:
    "Handler for one connection"

    def __init__(self, server, client):
        self.server = server
        self.client = client
        self.sem = anyio.Semaphore(10)
        self.framer = ModbusSocketFramer(ServerDecoder())
        self.send_lock = anyio.Lock()

    async def work(self, request):
        """Subtask to process a request, then send the reply"""
        unit_id = request.unit_id
        transaction_id = request.transaction_id
        try:
            try:
                unit = self.server.units[unit_id]
            except KeyError:
                response = ExceptionResponse(
                    request.function_code, ExceptionResponse.SLAVE_FAILURE
                )
            else:
                response = await unit.process_request(request)

            response.unit_id = unit_id
            response.transaction_id = transaction_id
            response = self.framer.buildFrame(response)
            try:
                async with self.send_lock:
                    await self.client.send(response)
            except (
                ConnectionResetError,
                anyio.ClosedResourceError,
                anyio.BrokenResourceError,
                anyio.EndOfStream,
            ):
                pass

        finally:
            self.sem.release()

    async def run(self):
        """Client task. Reads requests and starts handlers to
        process them asynchronously."""

        async with self.client, anyio.create_task_group() as tg:
            try:
                data = bytearray()
                while True:
                    data += await self.client.receive(4096)

                    msgs = []

                    while True:
                        used, pdu = self.framer.processIncomingFrame(data)
                        data = data[used:]
                        if pdu is None:
                            break
                        msgs.append(pdu)

                    for msg in msgs:
                        await self.sem.acquire()
                        tg.start_soon(self.work, msg)

            except (
                anyio.IncompleteRead,
                ConnectionRefusedError,
                ConnectionResetError,
                anyio.ClosedResourceError,
                ModbusIOException,
                anyio.BrokenResourceError,
                anyio.EndOfStream,
                TimeoutError,
            ):
                tg.cancel_scope.cancel()
                return


class Server:
    """
    A forwarding Modbus server.
    """

    def __init__(self, host=None, port=502):
        self.host = host
        self.port = port
        self.units = {}

    def attach(self, unit: int, dev):
        """Attach a Modbus device under this unit#"""
        self.units[unit] = dev

    async def run(self):
        """Run the server."""

        async def proc(client):
            fwd = Forwarder(self, client)
            await fwd.run()

        listener = await anyio.create_tcp_listener(local_host=self.host, local_port=self.port)
        await listener.serve(proc)
