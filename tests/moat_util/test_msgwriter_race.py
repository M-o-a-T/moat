"""Tests probing MsgWriter for concurrency hazards.

MsgWriter is shared between two cooperating tasks in
``moat.link.server.Server.save_stream`` (the initial-state walker and the
live-update streamer).  These tests check whether messages survive that
shared use without duplication or reordering.
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import MsgReader, MsgWriter

pytestmark = pytest.mark.anyio


async def _write_many(mw: MsgWriter, msgs: list[object]) -> None:
    for m in msgs:
        await mw(m)


async def test_msgwriter_concurrent_no_duplication(tmp_path):
    """When two tasks share a MsgWriter, every message must appear exactly once.

    The buffer flushes once ``curlen >= buflen``.  With ``buflen`` small
    enough to flush after every message, two tasks calling ``__call__``
    concurrently can race on ``self.buf`` and ``self.curlen``.

    This reproduces the root cause of "duplicated subtrees in places where
    they don't belong" reported against the moat.link server's
    ``save_stream`` path, which shares a single MsgWriter between the
    initial-state walker task and the live-update streamer task.
    """
    fname = tmp_path / "race.cbor"

    # Make buflen very small so the buffer flushes after almost every msg.
    # 32 bytes is enough room for a single small CBOR message but not two.
    msgs_a = [{"who": "A", "i": i, "pad": "a" * 50} for i in range(80)]
    msgs_b = [{"who": "B", "i": i, "pad": "b" * 50} for i in range(80)]

    async with (
        MsgWriter(path=fname, codec="std-cbor", buflen=32) as mw,
        anyio.create_task_group() as tg,
    ):
        tg.start_soon(_write_many, mw, msgs_a)
        tg.start_soon(_write_many, mw, msgs_b)

    seen: list[dict] = []
    async with MsgReader(path=fname, codec="std-cbor") as rdr:
        async for m in rdr:
            seen.append(m)

    # No corrupted entries
    for m in seen:
        assert isinstance(m, dict), m
        assert "who" in m, m
        assert "i" in m, m

    keys_seen = [(m["who"], m["i"]) for m in seen]
    keys_expected = sorted({("A", i) for i in range(80)} | {("B", i) for i in range(80)})
    assert len(keys_seen) == len(set(keys_seen)), (
        f"duplicates! file has {len(keys_seen)} msgs, "
        f"{len(keys_seen) - len(set(keys_seen))} duplicated"
    )
    assert sorted(keys_seen) == keys_expected, (
        set(keys_expected) - set(keys_seen),
        set(keys_seen) - set(keys_expected),
    )


async def test_msgwriter_concurrent_with_flush(tmp_path):
    """Concurrent ``__call__`` and ``flush`` must not duplicate or lose data.

    ``moat.link.server._save_stream`` calls ``mw.flush()`` periodically while
    another task may still be writing via ``mw(msg)``.
    """
    fname = tmp_path / "race_flush.cbor"
    msgs = [{"i": i, "pad": "x" * 40} for i in range(200)]

    async def flusher(mw: MsgWriter, stop: anyio.Event) -> None:
        while not stop.is_set():
            await anyio.lowlevel.checkpoint()
            await mw.flush(force=False)

    async with MsgWriter(path=fname, codec="std-cbor", buflen=32) as mw:
        stop = anyio.Event()
        async with anyio.create_task_group() as tg:
            tg.start_soon(flusher, mw, stop)
            await _write_many(mw, msgs)
            stop.set()

    seen: list[dict] = []
    async with MsgReader(path=fname, codec="std-cbor") as rdr:
        async for m in rdr:
            seen.append(m)

    keys_seen = [m["i"] for m in seen]
    assert len(keys_seen) == len(set(keys_seen)), (
        f"duplicates! {len(keys_seen) - len(set(keys_seen))} dups"
    )
    assert sorted(keys_seen) == list(range(200)), (
        set(range(200)) - set(keys_seen),
        set(keys_seen) - set(range(200)),
    )
