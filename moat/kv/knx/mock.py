"""
Test helpers for moat.kv.knx.

:class:`Tester` connects a single XKNX client to a local knxd daemon and
exposes convenience methods for creating xknx device proxies.

The simulated-device classes implement the *device* side of a KNX exchange —
i.e. the physical actuator or sensor on the bus — rather than the controller
side that xknx device proxies represent.  They react to bus telegrams directly
via ``telegram_received_cb``, without going through xknx device proxy classes.

Class hierarchy::

    SimulatedDevice (ABC)
    ├── SimulatedSensorDevice   – write-only sensor, no command address
    └── SimulatedActuatorBase (ABC)
        ├── SimulatedBinaryDevice  – bool state, DPT 1.x encoding
        └── SimulatedActuator      – numeric state, configurable DPTNumeric
"""

from __future__ import annotations

import anyio
import os
import tempfile
from abc import ABC, abstractmethod
from contextlib import asynccontextmanager

import xknx
from moat.lib.xknx.devices import BinarySensor, ExposeSensor, Sensor, Switch
from moat.lib.xknx.dpt import DPT2ByteFloat, DPTArray, DPTBinary, DPTNumeric
from moat.lib.xknx.io import ConnectionConfig, ConnectionType
from moat.lib.xknx.telegram import GroupAddress, Telegram
from moat.lib.xknx.telegram.apci import GroupValueRead, GroupValueResponse, GroupValueWrite

from typing import TYPE_CHECKING, Self

if TYPE_CHECKING:
    from anyio.abc import Process

    from moat.lib.xknx.telegram.address import GroupAddressableType

    from collections.abc import AsyncIterator


class SimulatedDevice(ABC):
    """
    Abstract base for all simulated KNX devices.

    Handles the *state address* side: puts outgoing state telegrams on the
    bus and answers :class:`~xknx.telegram.apci.GroupValueRead` requests.
    Subclasses must implement :meth:`_encode` to produce the payload.

    Args:
        device_xknx: Started XKNX instance representing the device side.
        state_addr: Group address on which the device publishes its state.
        extra_addrs: Additional addresses to subscribe to (used by
            :class:`SimulatedActuatorBase` to add the command address).
    """

    def __init__(
        self,
        device_xknx: xknx.XKNX,
        state_addr: GroupAddressableType,
        extra_addrs: list[GroupAddress] | None = None,
    ) -> None:
        """Initialise and register the telegram callback."""
        self._xknx = device_xknx
        self.state_addr: GroupAddress = GroupAddress(state_addr)
        watched = [self.state_addr, *(extra_addrs or [])]
        device_xknx.telegram_queue.register_telegram_received_cb(
            self._on_telegram,
            group_addresses=watched,
        )

    @abstractmethod
    def _encode(self) -> DPTBinary | DPTArray:
        """Encode the current device value into a KNX payload."""

    def _on_telegram(self, telegram: Telegram) -> None:
        """React to incoming telegrams.  Subclasses should call ``super()``."""
        if telegram.destination_address == self.state_addr:
            if isinstance(telegram.payload, GroupValueRead):
                self._send_state(response=True)

    def _send_state(self, *, response: bool) -> None:
        """Put a state telegram into the outgoing queue."""
        value = self._encode()
        payload: GroupValueWrite | GroupValueResponse
        if response:
            payload = GroupValueResponse(value=value)
        else:
            payload = GroupValueWrite(value=value)
        self._xknx.telegrams.put_nowait(
            Telegram(destination_address=self.state_addr, payload=payload)
        )


class SimulatedSensorDevice(SimulatedDevice):
    """
    Simulates a write-only KNX sensor (e.g. a temperature transmitter).

    The device has no command address.  It only publishes readings on
    *state_addr* and responds to
    :class:`~xknx.telegram.apci.GroupValueRead` requests.  Values are
    encoded with *dpt* (default: :class:`~xknx.dpt.DPT2ByteFloat`).

    Args:
        device_xknx: Started XKNX instance representing the device side.
        state_addr: Group address on which the device publishes its value.
        initial: Initial sensor value (default ``0.0``).
        dpt: DPT class used for encoding / decoding (default
            :class:`~xknx.dpt.DPT2ByteFloat`).
    """

    def __init__(
        self,
        device_xknx: xknx.XKNX,
        state_addr: GroupAddressableType,
        initial: float = 0.0,
        dpt: type[DPTNumeric] = DPT2ByteFloat,
    ) -> None:
        """Initialise and register the telegram callback."""
        super().__init__(device_xknx, state_addr)
        self.value: float = initial
        self._dpt: type[DPTNumeric] = dpt

    def _encode(self) -> DPTArray:
        """Encode the current value as a DPTArray."""
        return self._dpt.to_knx(self.value)

    def set_value(self, val: float) -> None:
        """
        Inject a new sensor reading onto the bus.

        Sends a :class:`~xknx.telegram.apci.GroupValueWrite` on the state
        address, as a real sensor would when its reading changes.

        Args:
            val: New value to publish.
        """
        self.value = val
        self._send_state(response=False)


class SimulatedBinarySensor(SimulatedDevice):
    """
    Simulates a write-only KNX binary sensor (e.g. a push button or motion
    detector).

    The device has no command address.  It only publishes its boolean state
    on *state_addr* and answers
    :class:`~xknx.telegram.apci.GroupValueRead` requests.

    :meth:`set_state` lets tests inject a state change as the physical
    sensor would.

    Args:
        device_xknx: Started XKNX instance representing the device side.
        state_addr: Group address on which the sensor publishes its state.
        initial: Initial boolean state (default ``False``).
    """

    def __init__(
        self,
        device_xknx: xknx.XKNX,
        state_addr: GroupAddressableType,
        initial: bool = False,
    ) -> None:
        """Initialise and register the telegram callback."""
        super().__init__(device_xknx, state_addr)
        self.state: bool = initial

    def _encode(self) -> DPTBinary:
        """Encode the boolean state as a :class:`~xknx.dpt.DPTBinary`."""
        return DPTBinary(1 if self.state else 0)

    def set_state(self, val: bool) -> None:
        """
        Inject a new sensor reading onto the bus.

        Sends a :class:`~xknx.telegram.apci.GroupValueWrite` on the state
        address, as a real sensor would when its physical input changes.

        Args:
            val: New boolean state to publish.
        """
        self.state = val
        self._send_state(response=False)


class SimulatedActuatorBase(SimulatedDevice, ABC):
    """
    Abstract base for simulated KNX actuators with a command address.

    Extends :class:`SimulatedDevice` with a *command address*: incoming
    :class:`~xknx.telegram.apci.GroupValueWrite` telegrams on *cmd_addr*
    are decoded by :meth:`_apply` and confirmed by sending the new state on
    *state_addr*.

    Subclasses must implement :meth:`_encode` and :meth:`_apply`.

    Args:
        device_xknx: Started XKNX instance representing the device side.
        cmd_addr: Group address on which the actuator receives commands.
        state_addr: Group address on which the actuator publishes its state.
    """

    def __init__(
        self,
        device_xknx: xknx.XKNX,
        cmd_addr: GroupAddressableType,
        state_addr: GroupAddressableType,
    ) -> None:
        """Initialise and register the telegram callback."""
        self.cmd_addr: GroupAddress = GroupAddress(cmd_addr)
        super().__init__(device_xknx, state_addr, extra_addrs=[self.cmd_addr])

    @abstractmethod
    def _apply(self, value: DPTBinary | DPTArray) -> None:
        """Update internal state from an incoming command payload."""

    def _on_telegram(self, telegram: Telegram) -> None:
        """Handle command writes in addition to state reads."""
        super()._on_telegram(telegram)
        if telegram.destination_address == self.cmd_addr:
            if isinstance(telegram.payload, GroupValueWrite):
                self._apply(telegram.payload.value)
                self._send_state(response=False)


class SimulatedBinaryDevice(SimulatedActuatorBase):
    """
    Simulates a KNX binary actuator (e.g. a relay or a light switch).

    Processes :class:`~xknx.telegram.apci.GroupValueWrite` telegrams on the
    command address as boolean on/off commands (DPT 1.x), confirms each
    command by sending the new state on the state address, and answers
    :class:`~xknx.telegram.apci.GroupValueRead` requests on the state
    address.

    :meth:`set_state` lets tests inject a device-originated state change.

    Args:
        device_xknx: Started XKNX instance representing the device side.
        cmd_addr: Group address on which the device receives commands.
        state_addr: Group address on which the device publishes its state.
    """

    def __init__(
        self,
        device_xknx: xknx.XKNX,
        cmd_addr: GroupAddressableType,
        state_addr: GroupAddressableType,
    ) -> None:
        """Initialise with state False and register the telegram callback."""
        super().__init__(device_xknx, cmd_addr, state_addr)
        self.state: bool = False

    def _encode(self) -> DPTBinary:
        """Encode the boolean state as a :class:`~xknx.dpt.DPTBinary`."""
        return DPTBinary(1 if self.state else 0)

    def _apply(self, value: DPTBinary | DPTArray) -> None:
        """Set state from the boolean payload of an incoming command."""
        if isinstance(value, DPTBinary):
            self.state = bool(value.value)

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


class SimulatedActuator(SimulatedActuatorBase):
    """
    Simulates a KNX numeric actuator (e.g. a dimmer or a setpoint controller).

    Accepts numeric commands encoded with *dpt* (default:
    :class:`~xknx.dpt.DPT2ByteFloat` for two-byte floats) on the command
    address, confirms each command, and answers
    :class:`~xknx.telegram.apci.GroupValueRead` requests on the state address.

    :meth:`set_state` lets tests inject a device-originated state change.

    Args:
        device_xknx: Started XKNX instance representing the device side.
        cmd_addr: Group address on which the actuator receives commands.
        state_addr: Group address on which the actuator publishes its state.
        initial: Initial state value (default ``0.0``).
        dpt: DPT class used for encoding and decoding (default
            :class:`~xknx.dpt.DPT2ByteFloat`).
    """

    def __init__(
        self,
        device_xknx: xknx.XKNX,
        cmd_addr: GroupAddressableType,
        state_addr: GroupAddressableType,
        initial: float = 0.0,
        dpt: type[DPTNumeric] = DPT2ByteFloat,
    ) -> None:
        """Initialise with the given state and DPT, register the callback."""
        super().__init__(device_xknx, cmd_addr, state_addr)
        self.state: float = initial
        self._dpt: type[DPTNumeric] = dpt

    def _encode(self) -> DPTArray:
        """Encode the current state as a :class:`~xknx.dpt.DPTArray`."""
        return self._dpt.to_knx(self.state)

    def _apply(self, value: DPTBinary | DPTArray) -> None:
        """Decode and store an incoming numeric command payload."""
        result = self._dpt.from_knx(value)
        self.state = float(result)

    def set_state(self, val: float) -> None:
        """
        Inject a device-originated state change.

        Sends a :class:`~xknx.telegram.apci.GroupValueWrite` on the state
        address without any preceding command.

        Args:
            val: New numeric state to publish.
        """
        self.state = val
        self._send_state(response=False)


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

    def switch(self, *a, **k) -> Switch:
        """Create a :class:`~xknx.devices.Switch` registered with the client."""
        assert self._client is not None
        res = Switch(self._client, *a, **k)
        self._client.devices.async_add(res)
        return res

    def binary_sensor(self, *a, **k) -> BinarySensor:
        """Create a :class:`~xknx.devices.BinarySensor` registered with the client."""
        assert self._client is not None
        res = BinarySensor(self._client, *a, **k)
        self._client.devices.async_add(res)
        return res

    def sensor(self, *a, **k) -> Sensor:
        """Create a :class:`~xknx.devices.Sensor` registered with the client."""
        assert self._client is not None
        res = Sensor(self._client, *a, **k)
        self._client.devices.async_add(res)
        return res

    def exposed_sensor(self, *a, **k) -> ExposeSensor:
        """Create an :class:`~xknx.devices.ExposeSensor` registered with the client."""
        assert self._client is not None
        res = ExposeSensor(self._client, *a, **k)
        self._client.devices.async_add(res)
        return res
