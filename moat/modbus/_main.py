"""
Basic "moat modbus" tool: network client and server, serial client
"""

from __future__ import annotations

import anyio
import sys
import traceback

import asyncclick as click

from moat.lib.modbus.framer import FramerRTU
from moat.lib.modbus.pdu import (
    PDU,
    ExceptionResponse,
    ReadCoilsRequest,
    ReadCoilsResponse,
    ReadDiscreteInputsRequest,
    ReadDiscreteInputsResponse,
    ReadHoldingRegistersRequest,
    ReadHoldingRegistersResponse,
    ReadInputRegistersRequest,
    ReadInputRegistersResponse,
    WriteMultipleCoilsRequest,
    WriteMultipleCoilsResponse,
    WriteMultipleRegistersRequest,
    WriteMultipleRegistersResponse,
    WriteSingleCoilRequest,
    WriteSingleCoilResponse,
    WriteSingleRegisterRequest,
    WriteSingleRegisterResponse,
)
from moat.lib.run import AliasedGroup, load_subgroup
from moat.modbus.client import ModbusClient
from moat.modbus.server import RelayServer, SerialModbusServer

from .__main__ import add_serial_cfg, mk_client, mk_serial_client, mk_server

import typing


@load_subgroup(sub_pre="moat.modbus")
async def cli():
    """Modbus tools"""
    pass


serialclient = mk_serial_client(cli)

client = mk_client(cli)
server = mk_server(cli)


# RTU inter-frame timeout for the passive monitor.  Matches the value
# used by the client/server readers; kept local so the CLI does not
# import internals from either.
_MONITOR_INTER_FRAME_TIMEOUT = 0.2


def print_exc(exc, **kw):  # pylint: disable=missing-function-docstring
    traceback.print_exception(type(exc), exc, exc.__traceback__, **kw)


# Friendly names for the function codes we recognise.
_FC_NAMES: dict[int, str] = {
    1: "Read Coils",
    2: "Read Discrete Inputs",
    3: "Read Holding Registers",
    4: "Read Input Registers",
    5: "Write Single Coil",
    6: "Write Single Register",
    15: "Write Multiple Coils",
    16: "Write Multiple Registers",
}


# Request PDU classes (decoded when the monitor is in the request phase).
_REQUEST_PDUS = (
    ReadCoilsRequest,
    ReadDiscreteInputsRequest,
    ReadHoldingRegistersRequest,
    ReadInputRegistersRequest,
    WriteSingleCoilRequest,
    WriteSingleRegisterRequest,
    WriteMultipleCoilsRequest,
    WriteMultipleRegistersRequest,
)


def _format_pdu(pdu: PDU) -> str:
    """Render a decoded PDU as a single human-readable line.

    Used by the passive monitor to dump each frame observed on the bus.
    """
    uid = getattr(pdu, "unit_id", 0)
    fc = pdu.function_code

    if isinstance(pdu, ExceptionResponse):
        return f"unit {uid}: Exception fc={fc} code={pdu.exception_code}"

    name = _FC_NAMES.get(fc, f"fc={fc}")

    if isinstance(pdu, (ReadCoilsRequest, ReadDiscreteInputsRequest)):
        return f"unit {uid}: {name} @{pdu.address} count={pdu.count}"
    if isinstance(pdu, (ReadHoldingRegistersRequest, ReadInputRegistersRequest)):
        return f"unit {uid}: {name} @{pdu.address} count={pdu.count}"
    if isinstance(pdu, WriteSingleCoilRequest):
        return f"unit {uid}: {name} @{pdu.address} ={'ON' if pdu.value else 'OFF'}"
    if isinstance(pdu, WriteSingleRegisterRequest):
        return f"unit {uid}: {name} @{pdu.address} ={pdu.value:#06x}"
    if isinstance(pdu, WriteMultipleCoilsRequest):
        bits = "".join("1" if b else "0" for b in pdu.bits)
        return f"unit {uid}: {name} @{pdu.address} count={pdu.count} bits={bits}"
    if isinstance(pdu, WriteMultipleRegistersRequest):
        regs = " ".join(f"{r:#06x}" for r in pdu.registers)
        return f"unit {uid}: {name} @{pdu.address} count={pdu.count} regs=[{regs}]"

    if isinstance(pdu, (ReadCoilsResponse, ReadDiscreteInputsResponse)):
        bits = "".join("1" if b else "0" for b in pdu.bits)
        return f"unit {uid}: {name} resp bits={bits}"
    if isinstance(pdu, (ReadHoldingRegistersResponse, ReadInputRegistersResponse)):
        regs = " ".join(f"{r:#06x}" for r in pdu.registers)
        return f"unit {uid}: {name} resp regs=[{regs}]"
    if isinstance(pdu, WriteSingleCoilResponse):
        return f"unit {uid}: {name} ack @{pdu.address}"
    if isinstance(pdu, WriteSingleRegisterResponse):
        return f"unit {uid}: {name} ack @{pdu.address} ={pdu.value:#06x}"
    if isinstance(pdu, WriteMultipleCoilsResponse):
        return f"unit {uid}: {name} ack @{pdu.address} count={pdu.count}"
    if isinstance(pdu, WriteMultipleRegistersResponse):
        return f"unit {uid}: {name} ack @{pdu.address} count={pdu.count}"

    # Fallback for anything unexpected.
    return f"unit {uid}: {pdu!r}"


async def _sniff_line(
    *,
    port: str,
    ser: dict[str, typing.Any],
    out: typing.IO[str],
    initial_timeout: float,
    idle_timeout: float,
    inter_frame_timeout: float = _MONITOR_INTER_FRAME_TIMEOUT,
) -> None:
    """Passively sniff a Modbus-RTU serial line and print every frame.

    Opens *port* receive-only (it never transmits), feeds the bytes to a
    monitor-role :class:`~moat.lib.modbus.framer.FramerRTU`, and prints
    each decoded frame prefixed with ``>`` (request) or ``<`` (response).

    Args:
        port: Serial device path.
        ser: Keyword arguments forwarded to ``anyio_serial.Serial``
            (baudrate, parity, stopbits, ...).
        out: Stream to write rendered frames to.
        initial_timeout: Seconds to wait for the very first byte; ``<=0``
            means wait forever.  Elapsing ends the sniff cleanly.
        idle_timeout: Seconds to wait for further bytes once data has been
            seen; ``<=0`` means wait forever.  Elapsing ends the sniff
            cleanly (the bus went quiet).
        inter_frame_timeout: Idle gap after which a partial frame is
            abandoned and the framer is reset to expecting a request.
    """
    from anyio_serial import Serial  # pylint: disable=import-outside-toplevel  # noqa: PLC0415

    framer = FramerRTU("monitor")
    saw_data = False

    async with Serial(port=port, **ser) as stream:
        while True:
            try:
                if framer.pending:
                    # A partial frame is in progress: bound the wait so a
                    # torn frame or a silent slave is recovered via
                    # resetFrame(), not held forever.
                    with anyio.fail_after(inter_frame_timeout):
                        chunk = await stream.receive(4096)
                elif initial_timeout > 0 and not saw_data:
                    with anyio.fail_after(initial_timeout):
                        chunk = await stream.receive(4096)
                elif idle_timeout > 0 and saw_data:
                    with anyio.fail_after(idle_timeout):
                        chunk = await stream.receive(4096)
                else:
                    chunk = await stream.receive(4096)
            except TimeoutError:
                if framer.pending:
                    # Abandon the stale partial frame and rephase to
                    # expecting a request; keep listening.
                    framer.resetFrame()
                    continue
                # Bus stayed quiet past the (initial/idle) deadline with
                # nothing pending: nothing more to see, stop cleanly.
                return

            saw_data = True

            # Feed only the freshly-received bytes; the framer owns the
            # accumulator and retains any surplus internally.  Repeatedly
            # call handleFrame with no new data to drain every complete
            # frame the chunk may contain.
            feed = bytes(chunk)
            while True:
                used, pdu = framer.handleFrame(feed)
                if pdu is not None:
                    # Direction from the PDU type itself (robust against
                    # the monitor's post-decode phase flip).
                    marker = ">" if isinstance(pdu, _REQUEST_PDUS) else "<"
                    out.write(f"{marker} {_format_pdu(pdu)}\n")
                    out.flush()
                if not used:
                    break
                # Further complete frames may sit in the framer's own
                # accumulator; feed nothing new to surface them.
                feed = b""


@cli.group(invoke_without_command=True, cls=AliasedGroup)
@add_serial_cfg
@click.option("-t", "--timeout", type=float, default=0, help="Error if no more data (seconds)")
@click.option(
    "-T",
    "--initial-timeout",
    "timeout1",
    type=float,
    default=0,
    help="Error if no data (seconds)",
)
@click.pass_context
async def monitor(ctx, timeout, timeout1, **params):
    """
    A basic Modbus RTU monitor.

    Without a subcommand this passively watches a Modbus RTU serial line
    and prints every frame it sees, marking requests with '>' and
    responses with '<'.  Nothing is transmitted.

    Add a "to" subcommand to instead relay the line to a server (useful
    for reverse engineering, serial speed/format translation, debugging);
    the arguments on the main command then describe the link to the
    client(s), i.e. the side acting as a Modbus client.
    """
    obj = ctx.obj

    if ctx.invoked_subcommand is not None:
        obj.A = params
        obj.timeout = timeout
        obj.timeout1 = timeout1
        return

    await _sniff_line(
        port=params["port"],
        ser={k: v for k, v in params.items() if k != "port"},
        out=obj.stdout,
        initial_timeout=timeout1,
        idle_timeout=timeout,
    )


@monitor.command
@add_serial_cfg
@click.option("-r", "--retry", type=int, help="Delay between restarts in case of errors")
@click.pass_obj
async def to(obj, retry, **params):
    """
    This subcommand describes the ModBus interface of the client(s).

    Useful for reverse engineering, serial speed/format translation, debugging …
    """
    A = None
    B = None

    class Server(RelayServer, SerialModbusServer):
        """A time-out-ing serial Modbus relay"""

        def __init__(self, *a, **kw):
            self.__evt = anyio.Event()
            super().__init__(*a, **kw)

        def mon_request(self, request):
            "request monitor"
            if isinstance(request, WriteSingleRegisterRequest):
                print(f"> {request}", request.value)
            else:
                print(f"> {request}", getattr(request, "registers", ""))
            return request

        def mon_response(self, response):
            "response monitor"
            print(f"< {response}", getattr(response, "registers", ""))
            self.__evt.set()
            return response

        async def watch(self, t2, t1):
            "Timeout manager"
            t = t1
            while True:
                if t is None:
                    await self.__evt.wait()
                else:
                    with anyio.fail_after(t):
                        await self.__evt.wait()
                t = t2
                self.__evt = anyio.Event()

    while True:
        try:
            async with (
                ModbusClient() as g_a,
                g_a.serial(**obj.A) as A,
                Server(client=A, **params) as B,
                # anyio.create_task_group() as tg,
            ):
                await B.watch(obj.timeout, obj.timeout1)
        except Exception as exc:  # pylint: disable=broad-exception-caught
            if not retry or not A or not B:
                raise
            print_exc(exc, file=sys.stderr)
            print(f"Retrying in {retry}s", file=sys.stderr)
            await anyio.sleep(retry)
