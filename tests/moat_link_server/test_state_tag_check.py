"""
Regression tests for state-file completeness checking.

Bug: ``tag_check`` required a ``CBOR_TAG_MOAT_FILE_END`` marker, so a
full-dump file that was truncated by a crash/power-loss *after* its
``CBOR_TAG_MOAT_CHANGE`` marker (which is emitted once the initial
full-state snapshot has been flushed) was wrongly rejected as incomplete.
On restart ``_read_saved_data`` then never set ``ready`` and
``_read_initial`` hung until ``server.timeout.startup`` (default 90s).

Fix: ``tag_check`` now accepts a full/init dump that carries either an
end marker or a change marker.
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import time as mtime
from moat.lib.codec.moat_cbor import gen_change, gen_start, gen_stop
from moat.link._test import Scaffold
from moat.link.meta import MsgMeta
from moat.link.server._server import tag_check
from moat.util.msg import MsgWriter

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.codec.cbor import Tag

pytestmark = pytest.mark.anyio


def _fid(mode: str = "full") -> Tag:
    """A file-ID start tag carrying the given mode.

    ``load_file`` unwraps the ``CBOR_TAG_CBOR_LEADER`` outer tag produced by
    ``gen_start`` before collecting the inner ``CBOR_TAG_MOAT_FILE_ID`` tag, so
    we replicate that here.
    """
    return gen_start("MoaT-Link test", mode=mode, name="t.moat").value


def test_complete_full_dump_with_end_marker_accepted():
    """A full dump with FILE_ID + FILE_END is complete (the classical case)."""
    assert tag_check([_fid("full"), gen_stop()])


def test_truncated_full_dump_with_change_marker_accepted():
    """A full dump with FILE_ID + CHANGE (no FILE_END) is complete.

    The change marker is emitted once the initial snapshot has been flushed,
    so a writer killed before the final end marker still leaves a usable dump.
    """
    assert tag_check([_fid("full"), gen_change(state=False)])


def test_init_dump_with_change_marker_accepted():
    """An init dump with a change marker is likewise complete."""
    assert tag_check([_fid("init"), gen_change()])


def test_incremental_dump_rejected_even_with_change():
    """An incremental (mode='incr') dump is never a complete anchor."""
    assert not tag_check([_fid("incr"), gen_change()])
    assert not tag_check([_fid("incr"), gen_stop()])


def test_dump_without_id_or_completion_rejected():
    """Missing FILE_ID, or neither end nor change marker, is incomplete."""
    # no FILE_ID
    assert not tag_check([gen_stop(), gen_change()])
    # FILE_ID but no completion marker at all
    assert not tag_check([_fid("full")])


def test_change_marker_among_other_tags_still_counts():
    """A change marker anywhere in the tag list completes a full dump."""
    fid = _fid("full")
    # FILE_ID, some change, more change, no end -> still complete
    assert tag_check([fid, gen_change(), gen_change()])


async def test_read_saved_data_accepts_truncated_full_with_change(cfg):
    """A server becomes ready when its only state file is a truncated full dump with a change marker.

    Plants a crafted file in the scaffold's save directory before starting the
    server.  Before the fix, ``_read_saved_data`` rejected it (no FILE_END) and
    ``_read_initial`` hung until ``server.timeout.startup``; after the fix the
    change marker makes the dump complete and the server starts promptly.
    """
    async with Scaffold(cfg, use_servers=True) as sf:
        # Plant a truncated full-dump file: header + one data record + CHANGE,
        # then a partial trailing byte (simulating a crash mid-record, no END).
        data_dir = anyio.Path(str(sf.tempdir)) / "data"
        await data_dir.mkdir(parents=True, exist_ok=True)
        fn = data_dir / "19-36.moat"
        meta = MsgMeta(origin="_file")
        meta.timestamp = mtime.time()
        async with MsgWriter(path=fn, codec="std-cbor") as mw:
            await mw(gen_start("MoaT-Link full 19-36.moat", mode="full", name="19-36.moat"))
            await mw([0, [], {"v": 1}, *meta.dump()])
            await mw(gen_change(state=False))
        # Append a partial CBOR byte (beginning of a map that never completes).
        async with await anyio.open_file(fn, "ab") as f:
            await f.write(b"\xa3")

        # Tighten the startup timeout so a regression fails fast.
        sf.cfg.server.timeout.startup = 5
        # Disable the MQTT-retention fallback so readiness must come from the file.
        sf.cfg.server.timeout.mqtt = 0

        # Starting the server must succeed (not time out).  _run_server blocks
        # on _read_initial becoming ready; a hang would trip the fail_after.
        # No ``init`` is passed: readiness must come from the planted file.
        with anyio.fail_after(sf.cfg.server.timeout.startup + 10):
            srv = await sf.server()
        assert srv is not None
