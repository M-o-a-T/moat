"""Smoke test: the ``moat db src`` command group loads and runs."""

from __future__ import annotations


async def test_group_runs(src):
    """The group loads (no import/loader errors) and ``list`` exits 0."""
    res = await src("list", ee=0)
    # Empty DB ⇒ the "no packages" hint reaches stderr/stdout; either way
    # the important assertion is that we got here without a crash.
    assert res is not None


async def test_add_then_list_shows_it(src):
    """Round-tripping add→list proves the SPKG leaf is wired."""
    await src("add", "smoke-pkg", ee=0)
    res = await src("list", ee=0)
    assert "smoke-pkg" in res.stdout
