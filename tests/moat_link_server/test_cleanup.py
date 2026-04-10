"""
Tests for the state-file cleanup logic in :mod:`moat.link.server._server`.
"""

from __future__ import annotations

import anyio
import logging
import pytest
from datetime import UTC, datetime

from moat.util import MsgWriter, attrdict
from moat.lib.codec.moat_cbor import gen_start, gen_stop
from moat.link.server._server import (
    Server,
    StateFileInfo,
    _read_state_header,
    _read_state_trailer,
)

from typing import Any

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_log = logging.getLogger("test.cleanup")


class _FakeServer:
    """Minimal stub used to call Server methods that only need a logger."""

    logger = _log


def make_save_cfg(**overrides: Any) -> attrdict:
    """Build a minimal ``server.save`` config attrdict.

    Args:
        **overrides: Override default config keys.
    """
    cfg: dict[str, Any] = {
        "keep": [2, "30 seconds"],
        "errors": 3,
    }
    cfg.update(overrides)
    return attrdict(**cfg)


async def make_state_file(
    path: anyio.Path,
    *,
    mode: str,
    timestamp: float,
    trailer_mode: str | None = None,
) -> None:
    """Write a minimal valid state file for testing.

    Args:
        path: Destination path.
        mode: Header mode (``'full'``, ``'incr'``, ``'init'``).
        timestamp: Start timestamp used in the header.
        trailer_mode: If given, written into the trailer as ``mode``.
            ``None`` emits a clean (non-error) trailer.
    """
    ts = datetime.fromtimestamp(timestamp, tz=UTC)
    async with MsgWriter(path=path, codec="std-cbor") as mw:
        await mw(gen_start(f"MoaT-Link {mode} test", mode=mode, time=ts, name=str(path)))
        kw: dict[str, Any] = {"time": datetime.now(UTC)}
        if trailer_mode is not None:
            kw["mode"] = trailer_mode
        await mw(gen_stop(**kw))


async def _make_file_list(
    base: anyio.Path,
    specs: list[tuple[str, float, str | None]],
) -> list[StateFileInfo]:
    """Create state files and return a newest-first :class:`StateFileInfo` list.

    Args:
        base: Directory to create files in.
        specs: List of ``(mode, timestamp, trailer_mode)`` tuples, newest first.
    """
    files: list[StateFileInfo] = []
    for i, (mode, ts, tmode) in enumerate(specs):
        fn = base / f"state_{i:04d}.moat"
        await make_state_file(fn, mode=mode, timestamp=ts, trailer_mode=tmode)
        trailer: dict[str, Any] | None = None
        if tmode is not None:
            trailer = {"mode": tmode}
        files.append(StateFileInfo(path=fn, timestamp=ts, mode=mode, trailer=trailer))
    return files


# ---------------------------------------------------------------------------
# Unit tests for header / trailer readers
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_read_state_header_full(tmp_path: Any) -> None:
    """_read_state_header returns correct timestamp and mode for a full file."""
    import time  # noqa: PLC0415

    fn = anyio.Path(tmp_path) / "test.moat"
    ts = time.time()
    await make_state_file(fn, mode="full", timestamp=ts)
    got_ts, got_mode = await _read_state_header(fn)
    assert got_mode == "full"
    assert abs(got_ts - ts) < 1.0


@pytest.mark.anyio
async def test_read_state_header_incr(tmp_path: Any) -> None:
    """_read_state_header returns mode='incr' for an incremental file."""
    fn = anyio.Path(tmp_path) / "incr.moat"
    await make_state_file(fn, mode="incr", timestamp=1000.0)
    _ts, mode = await _read_state_header(fn)
    assert mode == "incr"


@pytest.mark.anyio
async def test_read_state_trailer_clean(tmp_path: Any) -> None:
    """_read_state_trailer returns a dict without mode='error' for a clean file."""
    fn = anyio.Path(tmp_path) / "clean.moat"
    await make_state_file(fn, mode="full", timestamp=1000.0)
    trailer = await _read_state_trailer(fn)
    assert trailer is not None
    assert trailer.get("mode") != "error"


@pytest.mark.anyio
async def test_read_state_trailer_error(tmp_path: Any) -> None:
    """_read_state_trailer returns mode='error' for an error file."""
    fn = anyio.Path(tmp_path) / "err.moat"
    await make_state_file(fn, mode="full", timestamp=1000.0, trailer_mode="error")
    trailer = await _read_state_trailer(fn)
    assert trailer is not None
    assert trailer.get("mode") == "error"


@pytest.mark.anyio
async def test_read_state_trailer_missing(tmp_path: Any) -> None:
    """_read_state_trailer returns None for an incomplete (no trailer) file."""
    fn = anyio.Path(tmp_path) / "incomplete.moat"
    ts = datetime.fromtimestamp(1000.0, tz=UTC)
    # Write header only – no trailer
    async with MsgWriter(path=fn, codec="std-cbor") as mw:
        await mw(gen_start("test", mode="full", time=ts, name=str(fn)))
    trailer = await _read_state_trailer(fn)
    assert trailer is None


# ---------------------------------------------------------------------------
# Unit tests for _cleanup_state_files
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cleanup_count_only(tmp_path: Any) -> None:
    """keep=[2] keeps files at indices 0..2 and deletes index 3.

    After applying ``pos += 2`` (pos goes from 0 to 2), the end-of-keep rule
    deletes everything with index > 2, i.e. only the oldest file.
    """
    base = anyio.Path(tmp_path)
    specs = [
        ("full", 100.0, None),  # files[0]
        ("full", 90.0, None),  # files[1]
        ("full", 80.0, None),  # files[2]  ← pos lands here
        ("full", 70.0, None),  # files[3]  ← deleted
    ]
    files = await _make_file_list(base, specs)
    save = make_save_cfg(keep=[2])

    srv = _FakeServer()
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001

    # pos ends at 2 → files[0..2] kept, files[3] deleted
    assert len(files) == 3
    assert {f.timestamp for f in files} == {100.0, 90.0, 80.0}
    assert not await (base / "state_0003.moat").exists()
    assert await (base / "state_0002.moat").exists()


@pytest.mark.anyio
async def test_cleanup_interval(tmp_path: Any) -> None:
    """keep=[1, '20 seconds'] deletes intermediate files in the window."""
    base = anyio.Path(tmp_path)
    # timestamps: 100, 90, 80, 70, 60, 50
    specs = [
        ("full", 100.0, None),
        ("full", 90.0, None),
        ("full", 80.0, None),
        ("full", 70.0, None),
        ("full", 60.0, None),
        ("full", 50.0, None),
    ]
    files = await _make_file_list(base, specs)
    # keep=[1]: skip file[0] (t=100), pos → 1
    # "20 seconds" from pos=1 (t=90):
    #   90-80=10 ≤ 20 → span=1; 90-70=20 ≤ 20 → span=2; 90-60=30 > 20 → stop
    #   Delete file[2] (t=80).  pos → 2 (was pos+span=3, now 2 after deletion)
    # End: delete files[3:] → t=60, t=50
    save = make_save_cfg(keep=[1, "20 seconds"])

    srv = _FakeServer()
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001

    remaining = {f.timestamp for f in files}
    assert 100.0 in remaining  # skipped by count-1
    assert 90.0 in remaining  # left endpoint of window
    assert 80.0 not in remaining  # deleted (inside window)
    assert 70.0 in remaining  # right endpoint of window
    assert 60.0 not in remaining  # beyond keep entries
    assert 50.0 not in remaining  # beyond keep entries


@pytest.mark.anyio
async def test_cleanup_incr_files_preserved(tmp_path: Any) -> None:
    """Incremental files at the start of the list are preserved by the keep logic."""
    base = anyio.Path(tmp_path)
    # Newest files are incremental; the keep entry should advance past them
    specs = [
        ("incr", 100.0, None),  # newest, incremental
        ("incr", 95.0, None),  # incremental
        ("full", 90.0, None),  # first full
        ("full", 80.0, None),
        ("full", 70.0, None),
    ]
    files = await _make_file_list(base, specs)
    # keep=[1]: after advancing past 2 incr files, pos sits at files[2] (t=90).
    # Then pos += 1 → pos=3 (t=80).  End of keep: delete files[4:].
    save = make_save_cfg(keep=[1])

    srv = _FakeServer()
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001

    remaining = {f.timestamp for f in files}
    assert 100.0 in remaining  # incr, skipped past
    assert 95.0 in remaining  # incr, skipped past
    assert 90.0 in remaining  # full, pos was here before skip
    assert 80.0 in remaining  # full, pos ended up here
    assert 70.0 not in remaining  # deleted (beyond pos)


@pytest.mark.anyio
async def test_cleanup_error_within_limit(tmp_path: Any) -> None:
    """Error files within the errors limit are preserved."""
    base = anyio.Path(tmp_path)
    # errors_limit=3: pos=0,1,2 all < 3 → preserved; pos advances to 2 (first full)
    specs = [
        ("full", 100.0, "error"),  # pos=0, 0<3 → keep, pos→1
        ("full", 90.0, "error"),  # pos=1, 1<3 → keep, pos→2
        ("full", 80.0, None),  # pos=2, not error → apply keep entry
        ("full", 70.0, None),
    ]
    files = await _make_file_list(base, specs)
    # keep=[1], errors=3: error files advance pos to 2, then "1" → pos=3
    save = make_save_cfg(keep=[1], errors=3)

    srv = _FakeServer()
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001

    remaining = {f.timestamp for f in files}
    assert 100.0 in remaining  # error but within limit
    assert 90.0 in remaining  # error but within limit
    assert 80.0 in remaining  # full anchor
    assert 70.0 in remaining  # pos ended up here


@pytest.mark.anyio
async def test_cleanup_error_beyond_limit(tmp_path: Any) -> None:
    """Error files beyond the errors limit are deleted."""
    base = anyio.Path(tmp_path)
    specs = [
        ("full", 100.0, "error"),  # pos=0 < 2 → keep
        ("full", 90.0, "error"),  # pos=1 < 2 → keep
        ("full", 80.0, "error"),  # pos=2 >= 2 → DELETE
        ("full", 70.0, None),  # now at pos=2, not error → apply entry
        ("full", 60.0, None),
    ]
    files = await _make_file_list(base, specs)
    save = make_save_cfg(keep=[1], errors=2)

    srv = _FakeServer()
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001

    remaining = {f.timestamp for f in files}
    assert 100.0 in remaining  # error, within limit
    assert 90.0 in remaining  # error, within limit
    assert 80.0 not in remaining  # error, beyond limit → deleted
    assert 70.0 in remaining  # full anchor (pos=2 after error deletion)
    assert 60.0 in remaining  # pos=3 after keep[1]


@pytest.mark.anyio
async def test_cleanup_empty_list() -> None:
    """Cleanup with an empty file list terminates without error."""
    srv = _FakeServer()
    files: list[StateFileInfo] = []
    save = make_save_cfg(keep=[5, "1 day"])
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001
    assert files == []


@pytest.mark.anyio
async def test_cleanup_all_incr(tmp_path: Any) -> None:
    """If all files are incremental, cleanup terminates without deletion."""
    base = anyio.Path(tmp_path)
    specs = [
        ("incr", 100.0, None),
        ("incr", 90.0, None),
    ]
    files = await _make_file_list(base, specs)
    save = make_save_cfg(keep=[1])

    srv = _FakeServer()
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001
    assert len(files) == 2  # nothing deleted


@pytest.mark.anyio
async def test_cleanup_interval_no_files_in_window(tmp_path: Any) -> None:
    """With span=0 (no file fits in the interval), pos does not advance."""
    base = anyio.Path(tmp_path)
    # Timestamps far apart; "5 seconds" window cannot include any second file.
    specs = [
        ("full", 100.0, None),
        ("full", 50.0, None),  # 50 s apart > 5 s window
        ("full", 10.0, None),
    ]
    files = await _make_file_list(base, specs)
    # keep=["5 seconds"]: span=0 (100-50=50 > 5), pos stays 0, end → delete files[1:]
    save = make_save_cfg(keep=["5 seconds"])

    srv = _FakeServer()
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001

    assert len(files) == 1
    assert files[0].timestamp == 100.0


# ---------------------------------------------------------------------------
# Tests for missing-file handling
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_cleanup_missing_file_removed_from_list(tmp_path: Any) -> None:
    """A file deleted from disk is silently removed from the list."""
    base = anyio.Path(tmp_path)
    specs = [
        ("full", 100.0, None),  # files[0]
        ("full", 90.0, None),  # files[1] ← will be deleted from disk
        ("full", 80.0, None),  # files[2]
    ]
    files = await _make_file_list(base, specs)
    # Manually remove files[1] from disk
    await files[1].path.unlink()

    save = make_save_cfg(keep=[2])
    srv = _FakeServer()
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001

    # files[1] (t=90) must have been pruned from the list.
    # keep=[2]: pos advances past 2 existing files (t=100, t=80); nothing deleted.
    remaining = {f.timestamp for f in files}
    assert 90.0 not in remaining
    assert 100.0 in remaining
    assert 80.0 in remaining


@pytest.mark.anyio
async def test_cleanup_count_skips_missing(tmp_path: Any) -> None:
    """Integer skip only counts existing files; missing ones are dropped.

    With keep=[2] and files [t100, t90(gone), t80, t70, t60]:
    * t90 is pruned when encountered during the count loop.
    * The skip of 2 counts t100 (count=1) and t80 (count=2), leaving
      pos=2 pointing to t70 (the anchor after pruning).
    * The tail rule deletes files[3:] = [t60] only.
    """
    base = anyio.Path(tmp_path)
    specs = [
        ("full", 100.0, None),  # files[0]
        ("full", 90.0, None),  # files[1] ← deleted from disk
        ("full", 80.0, None),  # files[2]
        ("full", 70.0, None),  # files[3]
        ("full", 60.0, None),  # files[4]
    ]
    files = await _make_file_list(base, specs)
    await files[1].path.unlink()

    # After pruning t=90: files = [t100, t80, t70, t60]
    # keep=[2]: count t100 (pos→1, count=1) then t80 (pos→2, count=2)
    # pos=2 → anchor is t70; files[3:] = [t60] → deleted
    save = make_save_cfg(keep=[2])
    srv = _FakeServer()
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001

    remaining = {f.timestamp for f in files}
    assert 90.0 not in remaining  # pruned (missing from disk)
    assert 100.0 in remaining  # within the 2-skip
    assert 80.0 in remaining  # within the 2-skip
    assert 70.0 in remaining  # pos anchor (not deleted)
    assert 60.0 not in remaining  # beyond pos → deleted


@pytest.mark.anyio
async def test_cleanup_interval_drops_missing_intermediate(tmp_path: Any) -> None:
    """Missing files in the interval scan are dropped; endpoints still kept."""
    base = anyio.Path(tmp_path)
    specs = [
        ("full", 100.0, None),  # files[0]  ← left endpoint
        ("full", 90.0, None),  # files[1]  ← will be manually deleted
        ("full", 80.0, None),  # files[2]  ← right endpoint (100-80=20≤20)
        ("full", 70.0, None),  # files[3]
    ]
    files = await _make_file_list(base, specs)
    await files[1].path.unlink()

    # keep=["20 seconds"]: scan from pos=0 (t=100).
    # t=90 is missing → dropped; t=80: 100-80=20≤20 → span=1 (after the drop).
    # Files between pos=0 and pos+span=1 (exclusive): nothing to delete.
    # pos advances to 1 (was pos+span after deletion).  End: delete files[2:].
    save = make_save_cfg(keep=["20 seconds"])
    srv = _FakeServer()
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001

    remaining = {f.timestamp for f in files}
    assert 90.0 not in remaining  # pruned (missing from disk)
    assert 100.0 in remaining  # left endpoint
    assert 80.0 in remaining  # right endpoint
    assert 70.0 not in remaining  # beyond pos → deleted


@pytest.mark.anyio
async def test_cleanup_missing_incr_dropped(tmp_path: Any) -> None:
    """Non-existent incremental files in the pre-step are silently removed.

    With keep=[1] and files [incr t100(gone), full t90, full t80, full t70]:
    * The missing incr is pruned, leaving files = [t90, t80, t70].
    * Pre-step: pos=0 (t90, the first existing non-incr).
    * Apply 1: pos advances to 1 (t80).
    * Tail: files[2:] = [t70] → deleted.
    """
    base = anyio.Path(tmp_path)
    specs = [
        ("incr", 100.0, None),  # files[0] ← missing
        ("full", 90.0, None),  # files[1]
        ("full", 80.0, None),  # files[2]
        ("full", 70.0, None),  # files[3]
    ]
    files = await _make_file_list(base, specs)
    await files[0].path.unlink()

    save = make_save_cfg(keep=[1])
    srv = _FakeServer()
    await Server._cleanup_state_files(srv, files, save)  # noqa: SLF001

    remaining = {f.timestamp for f in files}
    assert 100.0 not in remaining  # was missing, pruned
    assert 90.0 in remaining  # pre-step anchor
    assert 80.0 in remaining  # pos landed here
    assert 70.0 not in remaining  # beyond pos → deleted


# ---------------------------------------------------------------------------
# Tests for relative file names in headers / trailers
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_name_for_file_relative(tmp_path: Any) -> None:
    """_name_for_file returns a path relative to save.dir for files inside it."""
    from moat.util import to_attrdict  # noqa: PLC0415

    save_dir = tmp_path / "data"
    save_dir.mkdir()
    cfg = to_attrdict({"server": {"save": {"dir": str(save_dir)}}})

    class _MinimalServer:
        """Stub that only provides cfg."""

        def __init__(self, c: Any) -> None:
            self.cfg = c

    # A file inside save.dir
    inside = anyio.Path(save_dir) / "2024-01" / "01" / "10-00.moat"
    srv = _MinimalServer(cfg)
    result = Server._name_for_file(srv, inside)  # noqa: SLF001
    assert not result.startswith("/"), "Expected relative path, got: " + result
    assert result == str(anyio.Path(inside).relative_to(anyio.Path(save_dir)))

    # A file outside save.dir stays absolute
    outside = anyio.Path(tmp_path) / "other.moat"
    result2 = Server._name_for_file(srv, outside)  # noqa: SLF001
    assert result2 == str(outside)


@pytest.mark.anyio
async def test_header_stores_relative_name(cfg: Any, tmp_path: Any) -> None:
    """Headers written by the server embed a relative name, not an absolute path.

    Scaffold always puts state files in ``tempdir/data``; passing the test's
    ``tmp_path`` as ``tempdir`` makes that directory predictable.
    """
    from moat.util import MsgReader  # noqa: PLC0415
    from moat.lib.codec.cbor import CBOR_TAG_CBOR_LEADER, Tag  # noqa: PLC0415
    from moat.lib.codec.moat_cbor import CBOR_TAG_MOAT_FILE_ID  # noqa: PLC0415
    from moat.link._test import Scaffold  # noqa: PLC0415
    from moat.util.dict import combine_dict  # noqa: PLC0415

    # Short cycle so that at least one full file finishes writing.
    # interval must exceed the 1-second granularity of %H-%M-%S.
    save_cfg = {
        "name": "%Y-%m/%d/%H-%M-%S.moat",
        "interval": 1.2,
        "rewrite": 1,
        "errors": 10,
        "keep": [5],
    }
    override = attrdict(link=attrdict(server=attrdict(save=attrdict(**save_cfg))))
    merged_cfg = combine_dict(override, cfg, cls=attrdict)

    # Scaffold overwrites save.dir with tempdir/data; use tmp_path so we know where.
    # The directory must exist before the server starts (_save_task checks is_dir).
    data_dir = tmp_path / "data"
    data_dir.mkdir()

    async with Scaffold(merged_cfg, use_servers=True, tempdir=str(tmp_path)) as sf:
        await sf.server(init={"test": 1})
        await anyio.sleep(2.0)  # let at least one full cycle complete
    moat_files = list(data_dir.rglob("*.moat"))
    assert moat_files, f"No state files in {data_dir}"

    # All stored 'name' values must be relative (no leading '/').
    for fn in moat_files:
        async with MsgReader(anyio.Path(fn), codec="std-cbor") as rdr:
            raw = await anext(rdr)
        if isinstance(raw, Tag) and raw.tag == CBOR_TAG_CBOR_LEADER:
            raw = raw.value
        assert isinstance(raw, Tag)
        assert raw.tag == CBOR_TAG_MOAT_FILE_ID
        _text, meta = raw.value
        stored_name = meta.get("name", "")
        assert stored_name, f"{fn}: no 'name' in header"
        assert not stored_name.startswith("/"), f"{fn}: header 'name' is absolute: {stored_name!r}"


# ---------------------------------------------------------------------------
# Integration test: cleanup runs inside a live server
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_server_cleanup_integration(cfg: Any, tmp_path: Any) -> None:
    """After several save cycles, old files are cleaned up by the server."""
    from moat.link._test import Scaffold  # noqa: PLC0415
    from moat.util.dict import combine_dict  # noqa: PLC0415

    data_dir = tmp_path / "data"
    data_dir.mkdir()

    # Tight intervals so the test doesn't take too long.
    # keep=[1]: keep only the 1 most recent full file.
    save_cfg = {
        "dir": str(data_dir),
        "name": "%Y-%m/%d/%H-%M-%S.moat",
        "interval": 0.3,
        "rewrite": 2,
        "errors": 10,
        "keep": [1],
    }
    override = attrdict(link=attrdict(server=attrdict(save=attrdict(**save_cfg))))
    merged_cfg = combine_dict(override, cfg, cls=attrdict)

    async with Scaffold(merged_cfg, use_servers=True) as sf:
        await sf.server(init={"test": 1})
        # Let several save cycles run
        await anyio.sleep(1.2)

    # After ≥3 cycles with keep=[1], at most 2 .moat files should survive
    # (the current open one + the anchor).
    moat_files = list(data_dir.rglob("*.moat"))
    assert len(moat_files) <= 2, f"Too many state files: {moat_files}"
