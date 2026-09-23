"""Tests for the passive Modbus-RTU line monitor (``moat modbus monitor``).

Exercises :func:`moat.modbus._main._sniff_line` -- the receive-only sniffer
built on the monitor-role :class:`~moat.lib.modbus.framer.FramerRTU` -- against
a fake serial stream, so no hardware is required.  Covers frame rendering,
request/response direction markers, inter-frame-timeout recovery, and the
initial/idle timeout termination semantics.
"""

from __future__ import annotations

import anyio
import io
import pytest

from moat.modbus._main import _format_pdu, _sniff_line

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# --------------------------------------------------------------------------- #
# Fake serial stream
# --------------------------------------------------------------------------- #


class _FakeSerial:
    """A minimal stand-in for ``anyio_serial.Serial``.

    Yields scripted byte chunks from ``receive()`` in order.  Once the
    script is exhausted, ``receive()`` blocks forever (simulating a quiet
    bus), letting the surrounding timeout logic terminate the sniff.
    """

    def __init__(self, chunks: Iterable[bytes]):
        self._chunks = list(chunks)
        self._idx = 0
        self.open = True

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_tb):
        self.open = False

    async def receive(self, _max_bytes: int = 4096) -> bytes:
        if self._idx >= len(self._chunks):
            # Quiet bus: park until cancelled (the timeout will fire).
            await anyio.sleep_forever()
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk


def _patch_serial(monkeypatch, chunks: Iterable[bytes]) -> _FakeSerial:
    """Patch ``anyio_serial.Serial`` to return a :class:`_FakeSerial`."""
    fake_holder: list[_FakeSerial] = []

    def factory(*_a, **_kw):
        fake = _FakeSerial(list(chunks))
        fake_holder.append(fake)
        return fake

    import anyio_serial  # noqa: PLC0415

    monkeypatch.setattr(anyio_serial, "Serial", factory)
    return fake_holder[0] if fake_holder else _FakeSerial([])


# Helper: build a real RTU frame for a given PDU using a throwaway framer.
from moat.lib.modbus.framer import FramerRTU  # noqa: E402
from moat.lib.modbus.pdu import (  # noqa: E402
    ExceptionResponse,
    ReadCoilsRequest,
    ReadCoilsResponse,
    ReadHoldingRegistersRequest,
    ReadHoldingRegistersResponse,
    WriteMultipleRegistersRequest,
    WriteMultipleRegistersResponse,
    WriteSingleCoilRequest,
    WriteSingleRegisterRequest,
)


def _frame(pdu) -> bytes:
    return FramerRTU(False).buildFrame(pdu)


# --------------------------------------------------------------------------- #
# _format_pdu
# --------------------------------------------------------------------------- #


def test_format_pdu_reads_and_writes():
    """_format_pdu renders the salient fields of each PDU kind."""
    assert (
        _format_pdu(ReadHoldingRegistersRequest(address=100, count=5, unit_id=1))
        == "unit 1: Read Holding Registers @100 count=5"
    )
    assert (
        _format_pdu(ReadHoldingRegistersResponse(registers=[1, 2, 3], unit_id=1))
        == "unit 1: Read Holding Registers resp regs=[0x0001 0x0002 0x0003]"
    )
    assert (
        _format_pdu(WriteSingleCoilRequest(address=5, bits=[True], unit_id=2))
        == "unit 2: Write Single Coil @5 =ON"
    )
    assert (
        _format_pdu(WriteSingleRegisterRequest(address=9, registers=[0xABCD], unit_id=3))
        == "unit 3: Write Single Register @9 =0xabcd"
    )
    assert (
        _format_pdu(ReadCoilsResponse(bits=[True, False], unit_id=4))
        == "unit 4: Read Coils resp bits=10"
    )
    exc = ExceptionResponse(function_code=3, exception_code=2)
    exc.unit_id = 7
    assert _format_pdu(exc) == "unit 7: Exception fc=3 code=2"


# --------------------------------------------------------------------------- #
# _sniff_line end-to-end
# --------------------------------------------------------------------------- #


@pytest.mark.trio
async def test_sniff_request_then_response(autojump_clock, monkeypatch):
    """A request followed by its reply prints '> request' then '< response'."""
    autojump_clock.autojump_threshold = 0.01

    req = ReadHoldingRegistersRequest(address=100, count=5, unit_id=1)
    resp = ReadHoldingRegistersResponse(registers=[1, 2, 3], unit_id=1)
    chunks = [_frame(req), _frame(resp)]

    _patch_serial(monkeypatch, chunks)
    out = io.StringIO()

    # idle_timeout terminates the sniff once the (fake) bus goes quiet.
    await _sniff_line(
        port="/dev/null",
        ser={"baudrate": 9600},
        out=out,
        initial_timeout=0,
        idle_timeout=0.05,
    )

    lines = out.getvalue().strip().splitlines()
    assert lines == [
        "> unit 1: Read Holding Registers @100 count=5",
        "< unit 1: Read Holding Registers resp regs=[0x0001 0x0002 0x0003]",
    ]


@pytest.mark.trio
async def test_sniff_direction_markers_flip_each_pair(autojump_clock, monkeypatch):
    """Two request/response pairs alternate '>' and '<' markers."""
    autojump_clock.autojump_threshold = 0.01

    frames = []
    for _ in range(2):
        frames.append(_frame(ReadCoilsRequest(address=0, count=4, unit_id=2)))
        frames.append(_frame(ReadCoilsResponse(bits=[True, False, True, False], unit_id=2)))

    _patch_serial(monkeypatch, frames)
    out = io.StringIO()

    await _sniff_line(
        port="/dev/null",
        ser={},
        out=out,
        initial_timeout=0,
        idle_timeout=0.05,
    )

    marks = [ln[0] for ln in out.getvalue().strip().splitlines()]
    assert marks == [">", "<", ">", "<"]


@pytest.mark.trio
async def test_sniff_split_chunks_accumulate(autojump_clock, monkeypatch):
    """Frames split across receives still decode once complete."""
    autojump_clock.autojump_threshold = 0.01

    req = ReadHoldingRegistersRequest(address=7, count=1, unit_id=4)
    frame = _frame(req)
    # Deliver the frame byte-by-byte across many receives.
    chunks = [frame[i : i + 1] for i in range(len(frame))]

    _patch_serial(monkeypatch, chunks)
    out = io.StringIO()

    await _sniff_line(
        port="/dev/null",
        ser={},
        out=out,
        initial_timeout=0,
        idle_timeout=0.05,
    )

    lines = out.getvalue().strip().splitlines()
    assert lines == ["> unit 4: Read Holding Registers @7 count=1"]


@pytest.mark.trio
async def test_sniff_torn_frame_recovers(autojump_clock, monkeypatch):
    """A torn partial frame + silence + a fresh frame decodes cleanly."""
    autojump_clock.autojump_threshold = 0.01

    req = ReadHoldingRegistersRequest(address=1, count=2, unit_id=1)
    good = _frame(req)

    # Chunk 1: a torn fragment (too short to decode).  Then the fake bus
    # goes quiet long enough to trip the inter-frame timeout, after which
    # the next chunk delivers a complete frame.
    chunks = [good[:3], good]

    _patch_serial(monkeypatch, chunks)
    out = io.StringIO()

    await _sniff_line(
        port="/dev/null",
        ser={},
        out=out,
        initial_timeout=0,
        idle_timeout=0.05,
        inter_frame_timeout=0.02,
    )

    lines = out.getvalue().strip().splitlines()
    assert lines == ["> unit 1: Read Holding Registers @1 count=2"]


@pytest.mark.trio
async def test_sniff_initial_timeout_ends_cleanly(autojump_clock, monkeypatch):
    """If no byte ever arrives within initial_timeout, the sniff exits quietly."""
    autojump_clock.autojump_threshold = 0.01

    _patch_serial(monkeypatch, [])  # bus never produces data
    out = io.StringIO()

    await _sniff_line(
        port="/dev/null",
        ser={},
        out=out,
        initial_timeout=0.05,
        idle_timeout=0,
    )

    assert out.getvalue() == ""


@pytest.mark.trio
async def test_sniff_idle_timeout_ends_after_quiet_period(autojump_clock, monkeypatch):
    """After seeing frames, a quiet bus past idle_timeout ends the sniff."""
    autojump_clock.autojump_threshold = 0.01

    req = ReadHoldingRegistersRequest(address=1, count=2, unit_id=1)
    # One frame, then silence.
    _patch_serial(monkeypatch, [_frame(req)])
    out = io.StringIO()

    await _sniff_line(
        port="/dev/null",
        ser={},
        out=out,
        initial_timeout=0,
        idle_timeout=0.05,
    )

    lines = out.getvalue().strip().splitlines()
    assert lines == ["> unit 1: Read Holding Registers @1 count=2"]


@pytest.mark.trio
async def test_sniff_exception_response_marked_as_response(autojump_clock, monkeypatch):
    """An exception response prints with the '<' marker."""
    autojump_clock.autojump_threshold = 0.01

    req = ReadHoldingRegistersRequest(address=1, count=2, unit_id=1)
    exc = ExceptionResponse(function_code=3, exception_code=2)
    exc.unit_id = 1
    chunks = [_frame(req), FramerRTU(True).buildFrame(exc)]

    _patch_serial(monkeypatch, chunks)
    out = io.StringIO()

    await _sniff_line(
        port="/dev/null",
        ser={},
        out=out,
        initial_timeout=0,
        idle_timeout=0.05,
    )

    lines = out.getvalue().strip().splitlines()
    assert lines == [
        "> unit 1: Read Holding Registers @1 count=2",
        "< unit 1: Exception fc=3 code=2",
    ]


@pytest.mark.trio
async def test_sniff_write_pair(autojump_clock, monkeypatch):
    """A write-multiple-registers request/acknowledgement pair renders."""
    autojump_clock.autojump_threshold = 0.01

    req = WriteMultipleRegistersRequest(address=10, registers=[1, 2, 3], unit_id=5)
    resp = WriteMultipleRegistersResponse(address=10, count=3, unit_id=5)
    _patch_serial(monkeypatch, [_frame(req), FramerRTU(True).buildFrame(resp)])
    out = io.StringIO()

    await _sniff_line(
        port="/dev/null",
        ser={},
        out=out,
        initial_timeout=0,
        idle_timeout=0.05,
    )

    lines = out.getvalue().strip().splitlines()
    assert lines == [
        "> unit 5: Write Multiple Registers @10 count=3 regs=[0x0001 0x0002 0x0003]",
        "< unit 5: Write Multiple Registers ack @10 count=3",
    ]
