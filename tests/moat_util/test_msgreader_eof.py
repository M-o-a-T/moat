"""Tests for :class:`moat.util.MsgReader` at end of input."""

from __future__ import annotations

import pytest

from moat.util import MsgReader

pytestmark = pytest.mark.anyio


async def test_yaml_last_doc_without_terminator(tmp_path):
    """The final YAML document is read even without a trailing ``---``."""
    src = tmp_path / "docs.yaml"
    src.write_text("- a\n- 1\n---\n- b\n- 2\n")

    async with MsgReader(path=src, codec="yaml") as rd:
        res = [msg async for msg in rd]
    assert res == [["a", 1], ["b", 2]]
