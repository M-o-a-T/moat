"""
Basic client/server tests
"""

from __future__ import annotations

import anyio
import pytest
import socket

from moat.lib.modbus import ExcCodes, ExceptionResponse
from moat.modbus.client import ModbusClient, ModbusError, _is_transient
from moat.modbus.server import ModbusServer
from moat.modbus.types import FloatValue, HoldingRegisters, LongValue, StringValue
from moat.util.exc import exc_iter


@pytest.mark.anyio
async def test_rw():
    """Your basic client/server read/write test"""
    async with ModbusServer(address="127.0.0.1", port=0) as srv:
        sru = srv.add_unit(12)
        srv1 = sru.add(HoldingRegisters, 34, LongValue(123456))
        srv2 = sru.add(HoldingRegisters, 36, FloatValue(9999.125))
        srv3 = sru.add(HoldingRegisters, 38, StringValue(10, "hélþ"))

        async with (
            ModbusClient() as cli,
            cli.host("127.0.0.1", srv.port) as clh,
            clh.unit(12) as clu,
            clu.slot("x") as cls,
        ):
            clv1 = cls.add(HoldingRegisters, 34, LongValue())
            clv2 = cls.add(HoldingRegisters, 36, FloatValue())
            clv3 = cls.add(HoldingRegisters, 38, StringValue(10))

            await cls.getValues()  # pylint:disable=protected-access
            assert clv1.value == 123456
            assert clv2.value == 9999.125
            assert clv3.value == "hélþ"

            c = sru.store["h"].changed
            assert not c.is_set()
            clv1._value_w = 345678  # noqa: SLF001
            clv2._value_w = clv2._value * 3  # noqa: SLF001
            clv3._value_w = "CoMiNg"  # noqa: SLF001
            await cls.setValues()  # pylint:disable=protected-access
            assert srv1.value == 345678
            assert srv2.value == 9999.125 * 3
            assert srv3.value == "CoMiNg"
            assert c.is_set()


@pytest.mark.anyio
async def test_missing_unit_error_is_clear_and_transient():
    """Reading a unit the server doesn't know about surfaces a clear,
    unwrapped ``ModbusError`` flagged as transient (so callers back off).

    Regression: previously this surfaced as a doubly-nested
    ``ExceptionGroup`` wrapping a message-less ``ModbusError()``.
    """
    err: ModbusError | None = None
    async with (
        ModbusServer(address="127.0.0.1", port=0) as srv,  # no units!
        ModbusClient() as cli,
        cli.host("127.0.0.1", srv.port) as clh,
        clh.unit(12) as clu,
        clu.slot("x") as cls,
    ):
        cls.add(HoldingRegisters, 34, LongValue())
        try:
            await cls.getValues()
        except BaseException as exc:  # unwrap the task-group nesting
            leaves = list(exc_iter(exc))
            err = leaves[-1] if leaves else exc
    assert isinstance(err, ModbusError)
    assert err.code is ExcCodes.GATEWAY_TARGET_NO_RESPONSE
    assert err.transient
    assert "unit not found" in str(err)


def test_modbus_error_messages_and_classification():
    """``ModbusError`` renders a human-readable message and classifies
    transient (retry-with-backoff) vs permanent (config bug) errors."""
    unit_gone = ModbusError(ExceptionResponse(3, ExcCodes.GATEWAY_TARGET_NO_RESPONSE))
    path_down = ModbusError(ExceptionResponse(3, ExcCodes.GATEWAY_PATH_UNAVAILABLE))
    bad_addr = ModbusError(ExceptionResponse(3, ExcCodes.ILLEGAL_DATA_ADDRESS))
    bad_func = ModbusError(ExceptionResponse(3, ExcCodes.ILLEGAL_FUNCTION))

    assert unit_gone.transient
    assert _is_transient(unit_gone)
    assert path_down.transient
    assert _is_transient(path_down)
    assert not bad_addr.transient
    assert not _is_transient(bad_addr)
    assert not bad_func.transient
    assert not _is_transient(bad_func)

    assert "unit not found" in str(unit_gone)
    assert "not reachable" in str(path_down)
    assert "illegal data address" in str(bad_addr)

    # Transport-level reachability errors are transient too.
    assert _is_transient(OSError("host unreachable"))
    assert _is_transient(TimeoutError())

    # Classification survives the double ExceptionGroup wrapping that
    # getValues()/readValues() produce.
    nested = ExceptionGroup("outer", [ExceptionGroup("inner", [unit_gone])])
    assert _is_transient(nested)


def _dead_port() -> int:
    """Return a TCP port that nothing is listening on."""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]
    finally:
        s.close()


@pytest.mark.anyio
async def test_unreachable_host_backoffs_instead_of_crashing(autojump_clock):  # noqa:ARG001
    """A host that can't be reached must not crash the client; the reader
    retries with backoff and the host context stays usable.

    Regression: previously ``connect_tcp`` raised a bare ``OSError`` that
    escaped ``tg.start(self._reader)`` and tore the whole daemon down.
    """
    port = _dead_port()
    # Entering the host context must succeed even though nothing answers.
    async with (
        ModbusClient() as cli,
        cli.host("127.0.0.1", port, timeout=0.2) as clh,
    ):
        assert not clh._connected.is_set()  # noqa:SLF001
        # Yield so the reader task gets to attempt (and fail) a couple of
        # connects.  With the autojump clock the backoff sleeps cost nothing.
        for _ in range(5):
            await anyio.sleep(0.5)
        # Still alive, still not connected, still retrying.
        assert not clh._connected.is_set()  # noqa:SLF001
    # Exiting the context cleanly proves the host didn't crash mid-flight.
