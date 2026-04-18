"""
Test helpers for moat.kv.knx.

:class:`Tester` connects a single XKNX client to a local knxd daemon and
exposes convenience methods for creating xknx device proxies.

:class:`SimulatedBinaryDevice` and :class:`SimulatedSensorDevice` simulate
real KNX actuators / sensors by reacting to bus telegrams directly, without
going through xknx device proxy classes.  They are intended for use in
end-to-end tests alongside a second XKNX instance that holds the controller
side (e.g. a :class:`~xknx.devices.Switch`).
"""

from __future__ import annotations

import anyio
import os
import tempfile
from contextlib import asynccontextmanager

import xknx
from xknx.devices import BinarySensor, ExposeSensor, Sensor, Switch
from xknx.dpt import DPT2ByteFloat, DPTArray, DPTBinary
from xknx.io import ConnectionConfig, ConnectionType
from xknx.telegram import GroupAddress, Telegram
from xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from anyio.abc import Process

    from xknx.telegram.address import GroupAddressableType

    from collections.abc import AsyncIterator


class SimulatedBinaryDevice:
    """
    Simulates a KNX binary actuator (e.g. a relay or a light switch).

    Registers a telegram callback on *device_xknx* that:

    - processes :class:`~xknx.telegram.apci.GroupValueWrite` telegrams
      arriving on *cmd_addr* by updating the internal state and sending a
      :class:`~xknx.telegram.apci.GroupValueWrite` confirmation on
      *state_addr*;
    - answers :class:`~xknx.telegram.apci.GroupValueRead` telegrams on
      *state_addr* with a :class:`~xknx.telegram.apci.GroupValueResponse`.

    :meth:`set_state` lets tests inject a device-originated state change
    (i.e. a write on *state_addr* without a preceding command).

    Args:
        device_xknx: The XKNX instance that represents the device side of
            the bus.  Must already be started.
        cmd_addr: Group address on which the device receives commands
            (``GroupValueWrite`` from a controller).
        state_addr: Group address on which the device publishes its state.
    """

    def __init__(
        self,
        device_xknx: xknx.XKNX,
        cmd_addr: GroupAddressableType,
        state_addr: GroupAddressableType,
    ) -> None:
        """Initialise and register the telegram callback."""
        self._xknx = device_xknx
        self.state: bool = False
        self.cmd_addr: GroupAddress = GroupAddress(cmd_addr)
        self.state_addr: GroupAddress = GroupAddress(state_addr)
        device_xknx.telegram_queue.register_telegram_received_cb(
            self._on_telegram,
            group_addresses=[self.cmd_addr, self.state_addr],
        )

    def _on_telegram(self, telegram: Telegram) -> None:
        """React to incoming telegrams on the command or state address."""
        if telegram.destination_address == self.cmd_addr:
            if isinstance(telegram.payload, GroupValueWrite):
                if isinstance(telegram.payload.value, DPTBinary):
                    self.state = bool(telegram.payload.value.value)
                self._send_state(response=False)
        elif telegram.destination_address == self.state_addr:
            if isinstance(telegram.payload, GroupValueRead):
                self._send_state(response=True)

    def _send_state(self, *, response: bool) -> None:
        """Put a state telegram into the outgoing queue."""
        payload: GroupValueWrite | GroupValueResponse
        value = DPTBinary(1 if self.state else 0)
        if response:
            payload = GroupValueResponse(value=value)
        else:
            payload = GroupValueWrite(value=value)
        self._xknx.telegrams.put_nowait(
            Telegram(destination_address=self.state_addr, payload=payload)
        )

    def set_state(self, val: bool) -> None:
        """
        Inject a device-originated state change.

        Sends a :class:`~xknx.telegram.apci.GroupValueWrite` on the state
        address without any preceding command, as a real device would when
        its physical input changes.

        Args:
            val: New boolean state to publish.
        """
        self.state = val
        self._send_state(response=False)


class SimulatedSensorDevice:
    """
    Simulates a write-only KNX sensor (e.g. a temperature transmitter).

    The device has no command address.  It only publishes readings on
    *state_addr* and responds to :class:`~xknx.telegram.apci.GroupValueRead`
    requests.  Values are encoded as 2-byte KNX floats (DPT 9.x).

    Args:
        device_xknx: The XKNX instance that represents the device side of
            the bus.  Must already be started.
        state_addr: Group address on which the device publishes its value.
        initial: Initial sensor value (default ``0.0``).
    """

    def __init__(
        self,
        device_xknx: xknx.XKNX,
        state_addr: GroupAddressableType,
        initial: float = 0.0,
    ) -> None:
        """Initialise and register the telegram callback."""
        self._xknx = device_xknx
        self.value: float = initial
        self.state_addr: GroupAddress = GroupAddress(state_addr)
        device_xknx.telegram_queue.register_telegram_received_cb(
            self._on_telegram,
            group_addresses=[self.state_addr],
        )

    def _on_telegram(self, telegram: Telegram) -> None:
        """Answer GroupValueRead requests on the state address."""
        if telegram.destination_address == self.state_addr:
            if isinstance(telegram.payload, GroupValueRead):
                self._send_value(response=True)

    def _send_value(self, *, response: bool) -> None:
        """Put a value telegram into the outgoing queue."""
        payload: GroupValueWrite | GroupValueResponse
        encoded: DPTArray = DPT2ByteFloat.to_knx(self.value)
        if response:
            payload = GroupValueResponse(value=encoded)
        else:
            payload = GroupValueWrite(value=encoded)
        self._xknx.telegrams.put_nowait(
            Telegram(destination_address=self.state_addr, payload=payload)
        )

    def set_value(self, val: float) -> None:
        """
        Inject a new sensor reading onto the bus.

        Sends a :class:`~xknx.telegram.apci.GroupValueWrite` on the state
        address, as a real sensor would when its reading changes.

        Args:
            val: New float value to publish.
        """
        self.value = val
        self._send_value(response=False)


class Tester:
    """
    Test helper that owns a knxd process and a single XKNX client.

    Use :meth:`run` as an async context manager to start both.  Convenience
    methods (:meth:`switch`, :meth:`binary_sensor`, etc.) create xknx device
    proxy objects already registered with the client.

    Args:
        port: TCP port that knxd will listen on.
    """

    _client: xknx.XKNX | None = None
    _server: object = None
    _socket: str | None = None

    def __init__(self, port: int) -> None:
        """Initialise with the TCP port knxd should use."""
        self.TCP_PORT = port

    @asynccontextmanager
    async def _daemon(self) -> AsyncIterator[Process]:
        """Start a knxd process and wait until it accepts connections."""
        with tempfile.TemporaryDirectory() as d:
            cfg = os.path.join(d, "test.ini")
            self._socket = os.path.join(d, "test.sock")
            with open(cfg, "w") as f:  # noqa:ASYNC230
                print(
                    f"""\
[main]
addr = 0.0.1
client-addrs = 0.0.2:8
connections = server,A.tcp

[A.tcp]
port = {self.TCP_PORT}
server = knxd_tcp
systemd-ignore = false

[server]
server = ets_router
tunnel = tunnel
port = {self.TCP_PORT}
discover = false

[tunnel]
""",
                    file=f,
                )
            proc = await anyio.open_process(["knxd", cfg])
            try:
                with anyio.fail_after(10):
                    while True:
                        try:
                            s = await anyio.connect_tcp("127.0.0.1", self.TCP_PORT)
                            await s.aclose()
                            break
                        except OSError:
                            await anyio.sleep(0.1)
                await anyio.sleep(0.2)
                yield proc
            finally:
                proc.terminate()
                with anyio.move_on_after(2) as cs:
                    cs.shield = True
                    await proc.wait()
                proc.kill()

    @asynccontextmanager
    async def run(self) -> AsyncIterator[Self]:
        """Start knxd and the XKNX client; yield *self*."""
        ccfg = ConnectionConfig(
            connection_type=ConnectionType.TUNNELING,
            gateway_ip="127.0.0.1",
            gateway_port=self.TCP_PORT,
        )
        async with (
            self._daemon() as server,
            xknx.XKNX(connection_config=ccfg) as client,
        ):
            self._server = server
            self._client = client
            yield self

    def switch(self, *a: object, **k: object) -> Switch:
        """Create a :class:`~xknx.devices.Switch` registered with the client."""
        assert self._client is not None
        res = Switch(self._client, *a, **k)
        self._client.devices.async_add(res)
        return res

    def binary_sensor(self, *a: object, **k: object) -> BinarySensor:
        """Create a :class:`~xknx.devices.BinarySensor` registered with the client."""
        assert self._client is not None
        res = BinarySensor(self._client, *a, **k)
        self._client.devices.async_add(res)
        return res

    def sensor(self, *a: object, **k: object) -> Sensor:
        """Create a :class:`~xknx.devices.Sensor` registered with the client."""
        assert self._client is not None
        res = Sensor(self._client, *a, **k)
        self._client.devices.async_add(res)
        return res

    def exposed_sensor(self, *a: object, **k: object) -> ExposeSensor:
        """Create an :class:`~xknx.devices.ExposeSensor` registered with the client."""
        assert self._client is not None
        res = ExposeSensor(self._client, *a, **k)
        self._client.devices.async_add(res)
        return res
