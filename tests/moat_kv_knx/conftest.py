"""
Test fixtures for moat.kv.knx end-to-end tests.

Three XKNX instances connect to a single knxd process:

- XKNX-A: the moat-side instance (created by the task under test)
- XKNX-B: simulates a real KNX device (``xknx_device`` fixture)
- XKNX-C: pure bus monitor (``xknx_monitor`` fixture)

knxd is configured with the ``dummy`` driver (no physical bus) and an
``ets_router`` server with tunneling enabled.  The same TCP/UDP port is used
for both the TCP readiness probe (``knxd_tcp`` server) and the KNXnet/IP
tunneling endpoint (``ets_router``).

xknx is asyncio-only, so all tests in this package run under asyncio.
"""

from __future__ import annotations

import anyio
import pytest
import subprocess

import xknx
from xknx.io import ConnectionConfig, ConnectionType

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from anyio.abc import TaskStatus

    from collections.abc import AsyncGenerator


@pytest.fixture
def anyio_backend() -> str:
    """Use asyncio as the anyio backend (xknx is asyncio-only)."""
    return "asyncio"


async def _run_knxd(port: int, *, task_status: TaskStatus[int]) -> None:
    """
    Start a knxd process and signal readiness.

    Args:
        port: TCP/UDP port for both the knxd_tcp readiness probe and the
            KNXnet/IP tunneling server.
        task_status: anyio task status; started with the port number once
            knxd is accepting connections.
    """
    async with anyio.TemporaryDirectory() as td:
        cfg_path = anyio.Path(td) / "knxd.ini"
        await cfg_path.write_text(
            f"""\
[main]
addr = 0.0.1
client-addrs = 0.0.2:8
connections = server,A.tcp

[A.tcp]
port = {port}
server = knxd_tcp
systemd-ignore = false

[server]
server = ets_router
tunnel = tunnel
port = {port}
discover = false

[tunnel]
"""
        )

        proc = await anyio.open_process(
            ["knxd", str(cfg_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        try:
            with anyio.fail_after(10):
                while True:
                    try:
                        sock = await anyio.connect_tcp("127.0.0.1", port)
                        await sock.aclose()
                        break
                    except OSError:
                        await anyio.sleep(0.1)
            # Give the UDP tunneling endpoint a moment to become ready too.
            await anyio.sleep(0.2)
            task_status.started(port)
            await anyio.sleep_forever()
        finally:
            proc.terminate()
            with anyio.CancelScope(shield=True):
                with anyio.move_on_after(2):
                    await proc.wait()
                proc.kill()


@pytest.fixture
async def knxd_port(free_tcp_port: int) -> AsyncGenerator[int, None]:
    """
    Start a knxd instance and yield the port it listens on.

    knxd is configured with a ``dummy`` driver (no physical bus) and
    KNXnet/IP tunneling via ``ets_router``.  Both the TCP readiness probe
    and the UDP tunneling endpoint use the same port number.

    Args:
        free_tcp_port: A free TCP port allocated by the anyio pytest plugin.

    Yields:
        The TCP/UDP port number that knxd listens on.
    """
    async with anyio.create_task_group() as tg:
        port: int = await tg.start(_run_knxd, free_tcp_port)
        yield port
        tg.cancel_scope.cancel()


def _make_ccfg(port: int) -> ConnectionConfig:
    """
    Build a KNXnet/IP tunneling connection config for the given port.

    Args:
        port: knxd tunneling port.
    """
    return ConnectionConfig(
        connection_type=ConnectionType.TUNNELING,
        gateway_ip="127.0.0.1",
        gateway_port=port,
    )


@pytest.fixture
async def xknx_device(knxd_port: int) -> AsyncGenerator[xknx.XKNX, None]:
    """
    A connected XKNX instance that simulates a real KNX device on the bus.

    Use this instance's ``telegram_queue.register_telegram_received_cb``
    to react to incoming telegrams and ``telegrams.put_nowait`` to inject
    telegrams as a device would.

    Args:
        knxd_port: Port of the running knxd instance.

    Yields:
        A started :class:`xknx.XKNX` instance.
    """
    async with xknx.XKNX(connection_config=_make_ccfg(knxd_port)) as client:
        yield client


@pytest.fixture
async def xknx_monitor(knxd_port: int) -> AsyncGenerator[xknx.XKNX, None]:
    """
    A connected XKNX instance used purely for bus monitoring.

    Register a ``telegram_received_cb`` (with ``match_for_outgoing=False``,
    the default) to capture all incoming telegrams as seen by this
    instance.  Because knxd routes telegrams to all tunnel clients, every
    telegram sent by any other connected instance will appear here as an
    incoming telegram.

    Args:
        knxd_port: Port of the running knxd instance.

    Yields:
        A started :class:`xknx.XKNX` instance.
    """
    async with xknx.XKNX(connection_config=_make_ccfg(knxd_port)) as client:
        yield client
