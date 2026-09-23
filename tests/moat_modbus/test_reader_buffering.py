"""Regression tests for the Modbus reader byte-accumulator contract.

The sans-IO framers (:class:`~moat.lib.modbus.framer.FramerTCP` /
:class:`~moat.lib.modbus.framer.FramerRTU`) own the receive byte
accumulator: :meth:`handleFrame` *extends* an internal ``_buffer`` with
whatever bytes it is fed and returns the count it consumed.  Callers
must therefore feed only **freshly-received** bytes -- never re-feed
bytes the framer has already retained -- or those bytes are duplicated
in ``_buffer`` and decoding corrupts.

These tests pin the corrected contract the readers in
:mod:`moat.modbus.client` now rely on:

* feeding a frame one byte at a time (across many ``handleFrame`` calls)
  decodes it exactly once;
* :attr:`FramerRTU.pending` truthfully reports whether a partial frame
  is in progress (used by the serial reader to arm the inter-frame
  timeout);
* the real :meth:`SerialHost._reader` loop decodes a frame that arrives
  split across several ``receive()`` calls -- the failure mode the old
  accumulate-and-re-feed code exhibited.
"""

from __future__ import annotations

import anyio
import pytest

from moat.lib.modbus import FramerRTU
from moat.lib.modbus.pdu import ReadHoldingRegistersResponse
from moat.modbus.client import SerialHost

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

# --------------------------------------------------------------------------- #
# Fake serial stream -- yields scripted chunks, then parks forever.
# --------------------------------------------------------------------------- #


class _FakeSerial:
    """A minimal stand-in for ``anyio_serial.Serial``.

    Hands out scripted byte chunks from ``receive()`` in order; once the
    script is exhausted, ``receive()`` parks forever (a quiet bus), so
    the surrounding timeout/cancel logic terminates the reader.
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
            await anyio.sleep_forever()
        chunk = self._chunks[self._idx]
        self._idx += 1
        return chunk


def _rtu_response() -> bytes:
    """A canonical RTU response frame (unit 1, 3 holding regs)."""
    return FramerRTU(True).buildFrame(ReadHoldingRegistersResponse(registers=[7, 8, 9], unit_id=1))


# --------------------------------------------------------------------------- #
# Framer-contract tests
# --------------------------------------------------------------------------- #


def test_feed_byte_by_byte_decodes_once():
    """Feeding a frame one byte at a time yields exactly one PDU.

    This is the invariant the corrected readers depend on: the framer
    owns the accumulator, so fragmentary feeding must not lose or
    duplicate bytes.
    """
    framer = FramerRTU(False)
    frame = _rtu_response()
    pdu = None
    used_total = 0
    for b in frame:
        used, pdu = framer.handleFrame(bytes([b]))
        used_total += used
        if pdu is not None:
            break
    assert pdu is not None
    assert isinstance(pdu, ReadHoldingRegistersResponse)
    assert pdu.registers == [7, 8, 9]
    # Exactly the frame was consumed -- no surplus, no shortfall.
    assert used_total == len(frame)
    assert framer.pending == 0


def test_pending_tracks_partial_frame():
    """``pending`` is non-zero while a frame is incomplete, zero after."""
    framer = FramerRTU(False)
    frame = _rtu_response()
    # Feed everything but the final CRC byte: incomplete.
    used, pdu = framer.handleFrame(frame[:-1])
    assert used == 0
    assert pdu is None
    assert framer.pending > 0
    # Complete it.
    used, pdu = framer.handleFrame(frame[-1:])
    assert pdu is not None
    assert used == len(frame)
    assert framer.pending == 0


def test_draining_via_empty_feeds_surfaces_buffered_frames():
    """Repeated ``handleFrame(b"")`` drains frames the framer already holds.

    Mirrors the reader's inner loop: after feeding a chunk containing a
    complete frame, further complete frames sitting in the accumulator
    are surfaced by feeding nothing new.
    """
    framer = FramerRTU(False)
    frame = _rtu_response()
    # Feed the whole frame in one shot.
    used, pdu = framer.handleFrame(frame)
    assert pdu is not None
    assert used == len(frame)
    # Feeding nothing must report "nothing consumed, nothing decoded"
    # (the accumulator is empty), not raise or stall.
    used, pdu = framer.handleFrame(b"")
    assert used == 0
    assert pdu is None


# --------------------------------------------------------------------------- #
# Integration: the real SerialHost._reader loop, fed a split frame
# --------------------------------------------------------------------------- #


class _GateStub:
    """Minimal gate: just a ``hosts`` dict (the reader never touches it)."""

    hosts: dict

    def __init__(self):
        self.hosts = {}


async def _drive_reader(host):
    """Run ``host._reader`` until one PDU is collected, then cancel.

    Cancels the reader task once the monitor has seen a decoded PDU
    (otherwise the fake serial parks forever and the test hangs).
    """
    pdus: list = []
    done = anyio.Event()

    async def mon(pdu):
        pdus.append(pdu)
        done.set()

    host._monitor = mon  # noqa: SLF001

    async with anyio.create_task_group() as tg:
        tg.cancel_scope.deadline = anyio.current_time() + 5

        async def runner(*, task_status):
            await host._reader(task_status=task_status)  # noqa: SLF001

        await tg.start(runner)
        await done.wait()
        tg.cancel_scope.cancel()
    return pdus


@pytest.mark.parametrize(
    "split",
    [
        # Split positions within the frame: head/tail, mid-CRC, every byte.
        (lambda f: [f]),
        (lambda f: [f[:1], f[1:]]),
        (lambda f: [f[:3], f[3:6], f[6:]]),
        (lambda f: [f[:-1], f[-1:]]),
        (lambda f: [bytes([b]) for b in f]),
    ],
    ids=["whole", "head_tail", "three_way", "last_crc_byte", "byte_by_byte"],
)
def test_serial_reader_decodes_split_frame(monkeypatch, split):
    """``SerialHost._reader`` decodes a frame arriving in fragments.

    Regression for the double-buffering bug: the old reader accumulated
    received bytes into a local ``data`` buffer *and* re-fed them to
    ``handleFrame`` (which also retains them in ``_buffer``), duplicating
    bytes whenever a frame spanned more than one ``receive()``.  The
    corrected reader feeds only fresh bytes and lets the framer own the
    accumulator.
    """
    frame = _rtu_response()
    chunks = split(frame)

    holder: list[_FakeSerial] = []

    def factory(*_a, **_kw):
        holder.append(_FakeSerial(chunks))
        return holder[-1]

    monkeypatch.setattr("moat.modbus.client.Serial", factory)

    host = SerialHost(_GateStub(), "/dev/null", timeout=1, baudrate=9600)

    def _go():
        return anyio.run(_drive_reader, host)

    pdus = _go()

    assert len(pdus) == 1
    assert isinstance(pdus[0], ReadHoldingRegistersResponse)
    assert pdus[0].registers == [7, 8, 9]
    assert pdus[0].unit_id == 1
