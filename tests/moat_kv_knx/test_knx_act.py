"""
End-to-end integration tests for moat.kv.knx actuator nodes.

The full stack under test is::

    moat-kv (via stdtest in-process server)
      └─ KNXroot model (two nodes: type=out on 0/0/1, type=in on 0/0/2)
          └─ XKNX-A  (moat side, created by task())
              └─ knxd (dummy driver + KNXnet/IP tunneling)
                  └─ XKNX-B / xknx_device (SimulatedBinaryDevice)

The ``xknx_device`` fixture and the ``anyio_backend`` override that forces
asyncio are defined in ``conftest.py``.  The ``knxd_port`` fixture starts a
knxd process.

.. note::

    ``moat.kv.mock.mqtt.stdtest`` normally expects to run under Trio (it uses
    ``trio.lowlevel.current_clock`` for the autojump clock).  Two guard lines
    in ``_stdtest`` make that call conditional, so the test infrastructure
    also works under asyncio for these KNX integration tests.
"""

from __future__ import annotations

import anyio
import pytest

from xknx.telegram import GroupAddress

from moat.util import attrdict
from moat.kv.knx.mock import SimulatedBinaryDevice, SimulatedBinarySensor
from moat.kv.knx.model import KNXroot
from moat.kv.knx.task import task
from moat.kv.mock.mqtt import stdtest
from moat.lib.path import P, Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import xknx

pytestmark = pytest.mark.anyio

# ── Fixed addresses and path names used throughout ──────────────────────── #

_PREFIX = P(":.moat.kv.knx")  # KNX model root in moat-kv
_KV_CMD = P("test.cmd")  # moat-kv path watched by the type=out node
_KV_STATE = P("test.state")  # moat-kv path written by the type=in node
_CMD_ADDR = GroupAddress("0/0/1")  # KNX command address  (type=out → bus)
_STATE_ADDR = GroupAddress("0/0/2")  # KNX state address   (bus → type=in)
_SENSOR_ADDR = GroupAddress("0/0/3")  # sensor-only address (bus → type=in)
_KV_SENSOR = P("test.sensor")  # moat-kv path written by the sensor type=in node
_BUS = "testbus"  # KNX bus name in the model tree
_SRV = "myserver"  # KNX server entry name in the model tree


async def test_moatkv_binary_roundtrip(
    knxd_port: int,
    xknx_device: xknx.XKNX,
) -> None:
    """
    Verify the full two-way binary actuator roundtrip through moat-kv-knx.

    The test exercises two directions:

    **moat-kv → device**: writing ``True`` / ``False`` to the moat-kv path
    watched by the ``type=out`` node causes a ``GroupValueWrite`` command on
    the KNX command address.  :class:`~moat.kv.knx.mock.SimulatedBinaryDevice`
    receives the command, updates its state, and sends a ``GroupValueWrite``
    confirmation on the state address.  The ``type=in`` node picks up that
    confirmation and writes it to a second moat-kv path.

    **device → moat-kv**: a device-originated state change (via
    :meth:`~moat.kv.knx.mock.SimulatedBinaryDevice.set_state`) publishes a
    ``GroupValueWrite`` on the state address.  The ``type=in`` node writes the
    new value into moat-kv, with no echo back to the command address.

    Args:
        knxd_port: Port of the running knxd instance (from fixture).
        xknx_device: Connected XKNX instance hosting the simulated device
            (from fixture).
    """
    cfg = attrdict(prefix=_PREFIX, server_default=attrdict(port=3671))

    device = SimulatedBinaryDevice(xknx_device, _CMD_ADDR, _STATE_ADDR)

    # tocks=50 gives enough headroom for config writes + test operations.
    async with stdtest(args={"init": 0}, tocks=50) as st:
        assert st is not None
        async with st.client() as c:
            # ── Populate the moat-kv KNX configuration tree ─────────────── #

            # Server entry: tells task() where knxd is.
            await c.set(
                _PREFIX + Path.build((_BUS, _SRV)),
                value={"host": "127.0.0.1", "port": knxd_port},
            )
            # type=out node: watches _KV_CMD and sends commands to _CMD_ADDR.
            await c.set(
                _PREFIX + Path.build((_BUS, 0, 0, 1)),
                value={"type": "out", "mode": "binary", "src": _KV_CMD},
            )
            # type=in node: listens on _STATE_ADDR and writes to _KV_STATE.
            await c.set(
                _PREFIX + Path.build((_BUS, 0, 0, 2)),
                value={"type": "in", "mode": "binary", "dest": _KV_STATE},
            )

            # ── Load the KNX model and start the moat-kv-knx task ───────── #

            knxroot = await KNXroot.as_handler(c, cfg=cfg)
            await knxroot.wait_loaded()

            task_ready = anyio.Event()

            # Collect every value written to _KV_STATE in order.
            st_send, st_recv = anyio.create_memory_object_stream[bool](max_buffer_size=16)

            async with anyio.create_task_group() as tg:
                # task() runs indefinitely; task_ready is its "started" signal.
                tg.start_soon(task, c, cfg, knxroot[_BUS][_SRV], task_ready)

                with anyio.fail_after(10):
                    await task_ready.wait()

                # Watch _KV_STATE; wait until the watch subscription is live
                # before sending any commands so we cannot miss the update.
                async def _watch(*, task_status=anyio.TASK_STATUS_IGNORED) -> None:
                    async with c.watch(_KV_STATE, min_depth=0, max_depth=0) as wp:
                        task_status.started()
                        async for msg in wp:
                            if "path" in msg and "value" in msg:
                                st_send.send_nowait(bool(msg.value))

                await tg.start(_watch)

                # Helper: consume from st_recv until the expected boolean is
                # seen.  This skips any earlier values, notably the initial
                # False written by _task_in's BinarySensor startup state-read
                # (it sends GroupValueRead → SimulatedBinaryDevice answers
                # GroupValueResponse(False) → _task_in writes test.state=False
                # before our first command is issued).
                async def _recv(expected: bool) -> None:
                    with anyio.fail_after(5):
                        async for val in st_recv:
                            if val is expected:
                                return

                # ── Direction 1: moat-kv → device → moat-kv ─────────────── #

                await c.set(_KV_CMD, value=True)
                await _recv(True)
                assert device.state is True

                await c.set(_KV_CMD, value=False)
                await _recv(False)
                assert device.state is False

                # ── Direction 2: device → moat-kv (no echo to bus) ──────── #

                device.set_state(True)
                await _recv(True)

                tg.cancel_scope.cancel()


async def test_moatkv_binary_sensor(
    knxd_port: int,
    xknx_device: xknx.XKNX,
) -> None:
    """
    Verify that moat-kv-knx correctly receives binary sensor readings.

    A :class:`~moat.kv.knx.mock.SimulatedBinarySensor` publishes boolean
    state changes on the sensor address (0/0/3).  The ``type=in`` node
    receives each ``GroupValueWrite`` and writes the value to ``test.sensor``
    in moat-kv.

    The ``type=in`` node's internal :class:`~xknx.devices.BinarySensor`
    issues a ``GroupValueRead`` at startup; the simulated sensor answers with
    ``GroupValueResponse(False)``, writing an initial ``False`` to moat-kv.
    The :func:`_recv` helper skips values until the expected one is seen,
    handling this start-up artifact transparently.

    Args:
        knxd_port: Port of the running knxd instance (from fixture).
        xknx_device: Connected XKNX instance hosting the simulated sensor
            (from fixture).
    """
    cfg = attrdict(prefix=_PREFIX, server_default=attrdict(port=3671))

    sensor = SimulatedBinarySensor(xknx_device, _SENSOR_ADDR)

    async with stdtest(args={"init": 0}, tocks=50) as st:
        assert st is not None
        async with st.client() as c:
            await c.set(
                _PREFIX + Path.build((_BUS, _SRV)),
                value={"host": "127.0.0.1", "port": knxd_port},
            )
            # type=in: sensor writes on 0/0/3 → moat-kv test.sensor
            await c.set(
                _PREFIX + Path.build((_BUS, 0, 0, 3)),
                value={"type": "in", "mode": "binary", "dest": _KV_SENSOR},
            )

            knxroot = await KNXroot.as_handler(c, cfg=cfg)
            await knxroot.wait_loaded()

            task_ready = anyio.Event()

            sens_send, sens_recv = anyio.create_memory_object_stream[bool](max_buffer_size=16)

            async with anyio.create_task_group() as tg:
                tg.start_soon(task, c, cfg, knxroot[_BUS][_SRV], task_ready)

                with anyio.fail_after(10):
                    await task_ready.wait()

                async def _watch_sensor(
                    *, task_status: anyio.abc.TaskStatus[None] = anyio.TASK_STATUS_IGNORED
                ) -> None:
                    async with c.watch(_KV_SENSOR, min_depth=0, max_depth=0) as wp:
                        task_status.started()
                        async for msg in wp:
                            if "path" in msg and "value" in msg:
                                sens_send.send_nowait(bool(msg.value))

                await tg.start(_watch_sensor)

                # Skip values until the expected one arrives.  The startup
                # GroupValueRead → GroupValueResponse(False) may pre-populate
                # test.sensor with False before the first explicit set_state().
                async def _recv(expected: bool) -> None:
                    with anyio.fail_after(5):
                        async for val in sens_recv:
                            if val is expected:
                                return

                sensor.set_state(True)
                await _recv(True)

                sensor.set_state(False)
                await _recv(False)

                tg.cancel_scope.cancel()
