"""
Modbus server classes for serial(RTU) and TCP.
"""

from __future__ import annotations

import anyio
import logging
import socket
import time
from anyio.abc import SocketAttribute
from binascii import b2a_hex
from contextlib import asynccontextmanager
from dataclasses import dataclass

from moat.util import CtxObj, ungroup
from moat.lib.modbus import (
    ExcCodes,
    ExceptionResponse,
    FramerRTU,
    FramerTCP,
)
from moat.lib.modbus.pdu import PDU, execute_request
from moat.modbus.types import BaseValue, DataBlock, TypeCodec

_logger = logging.getLogger(__name__)

__all__ = [
    "BaseModbusServer",
    "ModbusServer",
    "RelayServer",
    "SerialModbusServer",
    "UnitContext",
    "create_server",
]


# RTU inter-frame timeout (shared with the client side).
RTU_INTER_FRAME_TIMEOUT = 0.2


@dataclass
class Identity:
    """Modbus device identification (MEI type 0x2B).

    A simplified replacement for pymodbus'
    ``ModbusDeviceIdentification``.
    """

    VendorName: str = ""
    ProductCode: str = ""
    VendorUrl: str = ""
    ProductName: str = ""
    ModelName: str = ""
    MajorMinorRevision: str = ""


class UnitContext:
    """
    Standalone slave context for servers that stores individual variables.

    This replaces pymodbus' ``ModbusDeviceContext``.  It holds four
    :class:`~moat.modbus.types.DataBlock` instances keyed by ``c``
    (coils), ``d`` (discrete inputs), ``i`` (input registers), and
    ``h`` (holding registers), and exposes the :class:`Context`
    protocol that :meth:`moat.lib.modbus.pdu.Request.execute` consumes.
    """

    def __init__(self, server: BaseModbusServer | None = None, unit: int | None = None) -> None:
        self.store: dict[str, DataBlock] = {
            "c": DataBlock(),
            "d": DataBlock(),
            "i": DataBlock(),
            "h": DataBlock(),
        }
        self.unit = unit
        if server is not None and unit is not None:
            server._add_unit(self)  # noqa: SLF001

    def add(
        self,
        typ: TypeCodec,
        offset: int,
        val: BaseValue | type[BaseValue],
    ) -> BaseValue:
        """Add a field to be served.

        Args:
            typ: The ``TypeCodec`` instance to use.
            offset: The value's numeric offset, zero-based.
            val: The data type (``BaseValue`` subclass) or instance.

        Returns:
            The added ``BaseValue`` instance.
        """
        k = self.store[typ.key]
        if isinstance(val, type):
            val = val()
        k.add(offset, val)
        return val

    def remove(self, typ: TypeCodec, offset: int):
        """Remove a field.

        Args:
            typ: The ``TypeCodec`` to use.
            offset: The offset where the value is located.

        Returns:
            The removed field, or ``None`` if not found.
        """
        k = self.store[typ.key]
        return k.delete(offset + 1)

    # ---- Context protocol (consumed by moat.lib.modbus.pdu.Request.execute) ----

    def get_values(self, kind: str, address: int, count: int) -> list[int]:
        """Return *count* values starting at *address* for data kind *kind*.

        Addresses are 1-based (pymodbus convention) to match
        :meth:`DataBlock.getValues`.
        """
        block = self.store[kind]
        return block.getValues(address + 1, count)

    def set_values(self, kind: str, address: int, values: list[int]) -> None:
        """Set *values* starting at *address* for data kind *kind*.

        Addresses are 1-based (pymodbus convention) to match
        :meth:`DataBlock.setValues`.
        """
        block = self.store[kind]
        block.setValues(address + 1, values)

    # ---- camelCase aliases for backward compatibility ----

    def getValues(self, kind: str, address: int, count: int) -> list[int]:
        """Alias for :meth:`get_values`."""
        return self.get_values(kind, address, count)

    def setValues(self, kind: str, address: int, values: list[int]) -> None:
        """Alias for :meth:`set_values`."""
        self.set_values(kind, address, values)


class BaseModbusServer(CtxObj):
    """Basic base class for servers."""

    def __init__(self, identity: Identity | None = None, response_manipulator=None):
        self.units: dict[int, UnitContext] = {}
        self.broadcast_enable = False
        self.response_manipulator = response_manipulator
        self.ignored: set[int] = set()

        if identity is None:
            identity = Identity()
            identity.VendorName = "Matthias Urlichs"
            identity.ProductCode = "MoaT.modbus"
            identity.VendorUrl = "http://M-o-a-T.org/"
            identity.ProductName = "MoaT-Modbus Test"
            identity.ModelName = "MoaT-Modbus Test"
            identity.MajorMinorRevision = "1.0"
        self.identity = identity

    def add_unit(self, unit: int, ctx: UnitContext | None = None) -> UnitContext:
        """
        Add an empty unit (= slave context) to this server (and return it).

        The unit must not exist.
        """
        if unit in self.units:
            raise RuntimeError(f"Unit {unit} already exists")
        if ctx is None:
            return UnitContext(self, unit)
        self.units[unit] = ctx
        return ctx

    def add_ignored_unit(self, *unit: int) -> None:
        """
        Add to the list of units we don't complain about when a client
        tries to access them.
        """
        self.ignored |= set(unit)

    def _add_unit(self, unit_ctx: UnitContext) -> None:
        self.units[unit_ctx.unit] = unit_ctx

    async def serve(self, opened=None):
        """The actual server. Override me."""
        raise NotImplementedError("You need to override .serve")

    async def process_request(self, request: PDU) -> PDU:
        """Basic request processor."""
        try:
            context = self.units[request.unit_id]
        except KeyError:
            raise KeyError(request.unit_id) from None

        if hasattr(context, "process_request"):
            response = await context.process_request(request)
        else:
            response = execute_request(request, context)
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
    framer: FramerRTU
    ignore_missing_devices = False
    single = False

    def __init__(self, identity=None, timeout=None, **args):
        super().__init__(identity=identity)
        self.args = args
        self.timeout = timeout
        self.framer = FramerRTU(True)

    async def serve(self, opened=None):  # noqa: D102
        from anyio_serial import Serial  # pylint: disable=import-outside-toplevel  # noqa:PLC0415,I001

        async with Serial(**self.args) as ser:
            self._serial = ser

            if opened is not None:
                opened.set()
            t = time.monotonic()
            while True:
                with anyio.move_on_after(0.1):
                    await ser.receive()
                    break
            while True:
                try:
                    if self.timeout:
                        with anyio.fail_after(self.timeout):
                            data = await ser.receive()
                    else:
                        data = await ser.receive()
                except TimeoutError:
                    # Inter-frame timeout: reset and continue
                    self.framer.resetFrame()
                    continue

                t2 = time.monotonic()
                if t2 - t > RTU_INTER_FRAME_TIMEOUT:
                    self.framer.resetFrame()
                t = t2
                msgs: list[PDU] = []
                while True:
                    used, pdu = self.framer.handleFrame(bytes(data))
                    data = data[used:]
                    if pdu is None:
                        break
                    msgs.append(pdu)

                for msg in msgs:
                    with anyio.fail_after(2):
                        await self._process(msg)

    async def _process(self, request: PDU):
        broadcast = False
        unit = request.unit_id
        tid = request.transaction_id

        try:
            if self.broadcast_enable and not request.unit_id:
                broadcast = True
                # if broadcasting then execute on all slave contexts,
                # note response will be ignored
                for unit_id in self.units:
                    ctx = self.units[unit_id]
                    response = execute_request(request, ctx)
            else:
                response = await self.process_request(request)
        except KeyError:
            if unit not in self.ignored:
                _logger.error("requested unit does not exist: %d", request.unit_id)
            if self.ignore_missing_devices:
                return  # the client will simply timeout waiting for a response
            response = ExceptionResponse(request.function_code, ExcCodes.GATEWAY_NO_RESPONSE)
        except Exception:  # pylint: disable=broad-except
            _logger.exception("Unable to fulfill request")
            response = ExceptionResponse(request.function_code, ExcCodes.DEVICE_FAILURE)
        # no response when broadcasting
        response.unit_id = unit
        response.transaction_id = tid
        if isinstance(response, ExceptionResponse):
            _logger.error(
                "Source: %r %d %d %d %s",
                type(request).__name__,
                unit,
                getattr(request, "address", 0),
                getattr(request, "count", 1),
                response,
            )

        if not broadcast:
            response.transaction_id = request.transaction_id
            response.unit_id = request.unit_id
            skip_encoding = False
            if self.response_manipulator:
                response, skip_encoding = self.response_manipulator(response)
            if not skip_encoding:
                response = self.framer.buildFrame(response)

            await self._serial.send(response)


def create_server(cfg):
    """
    Create a server (TCP or serial) according to the configuration.

    @cfg is a dict with either host/port or port/serial keys.
    """
    if "serial" in cfg:
        port = cfg.get("port", None)
        kw = cfg["serial"]
        if port is not None:
            kw["port"] = port
        return SerialModbusServer(**kw)
    elif "host" in cfg or ("port" in cfg and isinstance(cfg["port"], int)):
        kw = {}
        for k, v in cfg.items():
            if isinstance(k, str):
                if k == "units":
                    continue
                if k == "host":
                    k = "address"  # noqa:PLW2901
                kw[k] = v
        return ModbusServer(**kw)
    else:
        raise ValueError("neither serial nor TCP config found")


class RelayServer:
    """
    A mix-in class to teach a server to forward all requests to a client
    """

    single = True

    def __init__(self, client, *a, **k):
        self._client = client
        super().__init__(*a, **k)

    async def _process(self, request: PDU):
        request = self.mon_request(request)
        tid = request.transaction_id
        resp = await self._client.execute(request)

        resp.transaction_id = tid
        resp = self.mon_response(resp) or resp
        resp = self.framer.buildFrame(resp)  # pylint:disable=no-member
        await self._serial.send(resp)  # pylint:disable=no-member

    def mon_request(self, request: PDU) -> PDU:
        """Request monitor. Override me."""
        return request

    def mon_response(self, response: PDU) -> PDU | None:
        """Response monitor. Override me."""
        return response


class ModbusServer(BaseModbusServer):
    """TCP Modbus server.

    If the identity structure is not passed in, a default is used.

    :param identity: An optional identity structure
    :param address: An optional address to bind to.
    :param port: the TCP port to listen on.
    """

    taskgroup = None
    single = False

    def __init__(self, identity=None, address=None, port=None):
        super().__init__(identity=identity)

        self.framer_cls = FramerTCP
        self.address = address or "localhost"
        self.port = port if port is not None else 502

    async def serve(self, opened: anyio.Event | None = None):
        """Run this server.

        Sets the ``opened`` event, if given, as soon as the server port is open.
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
        framer = FramerTCP(True)

        while True:
            try:
                data = await conn.receive(4096)
                if data == b"":
                    break
                if _logger.isEnabledFor(logging.DEBUG):
                    _logger.debug(  # pylint: disable=logging-not-lazy
                        "Handling data: " + b2a_hex(data).decode(),  # noqa:G003
                    )

                reqs: list[PDU] = []
                while True:
                    used, pdu = framer.handleFrame(bytes(data))
                    data = data[used:]
                    if pdu is None:
                        break
                    reqs.append(pdu)

                for request in reqs:
                    unit = request.unit_id
                    tid = request.transaction_id
                    try:
                        with ungroup:
                            response = await self.process_request(request)
                    except KeyError:
                        _logger.debug("requested unit does not exist: %d", request.unit_id)
                        response = ExceptionResponse(
                            request.function_code, ExcCodes.GATEWAY_NO_RESPONSE
                        )
                    except TimeoutError:
                        _logger.info("request to unit %d timed out", request.unit_id)
                        response = ExceptionResponse(
                            request.function_code, ExcCodes.GATEWAY_NO_RESPONSE
                        )
                    except Exception as exc:
                        _logger.warning("Unable to fulfill request", exc_info=exc)
                        response = ExceptionResponse(
                            request.function_code, ExcCodes.DEVICE_FAILURE
                        )
                    response.transaction_id = tid
                    response.unit_id = unit
                    pdu = framer.buildFrame(response)
                    if _logger.isEnabledFor(logging.DEBUG):
                        _logger.debug("send: %s", b2a_hex(pdu))
                    await conn.send(pdu)

            except TimeoutError as msg:
                _logger.debug("Socket timeout occurred: %r", msg)
                reset_frame = True
            except OSError as msg:
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
