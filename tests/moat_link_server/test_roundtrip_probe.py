"""Probe moat.link save/load round-trip for data integrity.

Targets the suspicion that PathShortener+save vs. load+PathLongener can
silently corrupt or duplicate subtrees in the saved file.
"""

from __future__ import annotations

import anyio
import pytest

from moat.util import NotGiven
from moat.lib.path import P, Path
from moat.link._test import Scaffold

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.node import Node

pytestmark = pytest.mark.anyio


async def _set_all(c, items):
    for p, v in items:
        await c.cmd(P("d.set"), P(p), v)


async def _fetch(c, p):
    async with c.d_watch(P(p), subtree=True, meta=True, state=True) as mon:
        return await mon.get_node()


def _flat(node: Node, base: Path = Path()) -> dict[str, object]:
    """Flatten a node subtree into {path_string: data}."""
    out: dict[str, object] = {}
    if node.data_ is not NotGiven:
        out[str(base)] = node.data_
    for k, v in node.items():
        out.update(_flat(v, base / k))
    return out


async def test_save_load_roundtrip_branchy(cfg, tmp_path):
    """Save & reload a wide branchy tree, verify the data tree is byte-identical."""
    fname = tmp_path / "rt.moat"
    items = [
        ("a", "A"),
        ("a.b", "AB"),
        ("a.b.c", "ABC"),
        ("a.b.c.d", "ABCD"),
        ("a.b.c.e", "ABCE"),
        ("a.b.f", "ABF"),
        ("a.g", "AG"),
        ("z", "Z"),
        ("z.w", "ZW"),
        ("z.w.v", "ZWV"),
    ]
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"test": 1})
        c = await sf.client()
        await _set_all(c, items)
        n_a = await _fetch(c, "a")
        n_z = await _fetch(c, "z")
        flat_a_before = _flat(n_a)
        flat_z_before = _flat(n_z)
        await c.cmd(P("s.save"), str(fname))

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"test": 2})
        c = await sf.client()
        await c.cmd(P("s.load"), str(fname))
        n_a = await _fetch(c, "a")
        n_z = await _fetch(c, "z")
        flat_a_after = _flat(n_a)
        flat_z_after = _flat(n_z)

    assert flat_a_before == flat_a_after, ("a subtree changed", flat_a_before, flat_a_after)
    assert flat_z_before == flat_z_after, ("z subtree changed", flat_z_before, flat_z_after)


async def test_save_load_no_cross_grafting(cfg, tmp_path):
    """Disjoint top-level subtrees must not bleed into each other."""
    fname = tmp_path / "rt2.moat"
    # Engineered so that path-shortener depth values transition oddly:
    # a.x.y.z.w (deep) then a.x.y.q (shorter sibling) then b (top) then z (top with shared name "x.y").
    items = [
        ("a.x.y.z.w", "deep1"),
        ("a.x.y.q", "shallow1"),
        ("b", "b-val"),
        ("b.c.d", "b-deep"),
        ("z", "z-val"),
        ("z.x.y", "z-mid"),  # shares suffix shape with a.x.y to provoke confusion
    ]
    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"test": 1})
        c = await sf.client()
        await _set_all(c, items)
        flat_before = {}
        for top in ("a", "b", "z"):
            flat_before[top] = _flat(await _fetch(c, top))
        await c.cmd(P("s.save"), str(fname))

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"test": 2})
        c = await sf.client()
        await c.cmd(P("s.load"), str(fname))
        flat_after = {}
        for top in ("a", "b", "z"):
            try:
                flat_after[top] = _flat(await _fetch(c, top))
            except KeyError:
                flat_after[top] = {}

    assert flat_before == flat_after, (flat_before, flat_after)


async def test_save_stream_with_live_updates(cfg, tmp_path):
    """save_stream writes both initial state and live updates; reload must reproduce all."""
    fname = tmp_path / "stream.moat"

    async with Scaffold(cfg, use_servers=True) as sf:
        srv = await sf.server(init={"test": 1})
        c = await sf.client()
        # initial state
        items_pre = [
            ("a", "A"),
            ("a.b", "AB"),
            ("a.b.c", "ABC"),
            ("a.b.c.d", "ABCD"),
            ("a.b.c.e", "ABCE"),
            ("zz", "ZZ"),
            ("zz.x", "ZZX"),
        ]
        await _set_all(c, items_pre)

        # Start streaming saver. save_state=True dumps current state too.
        await srv.run_saver(path=str(fname), save_state=True, wait=True)

        # Now apply interleaved live updates while the saver is running.
        items_post = [
            ("a.b.c.f", "ABCF-live"),
            ("a.b.g", "ABG-live"),
            ("zz.y", "ZZY-live"),
            ("new.deep.path", "new-live"),
        ]
        await _set_all(c, items_post)
        await anyio.sleep(0.5)

        # Stop the saver.
        await srv.run_saver(path=None, save_state=False, wait=False)
        await anyio.sleep(0.2)

        flat_before = {}
        for top in ("a", "zz", "new"):
            try:
                flat_before[top] = _flat(await _fetch(c, top))
            except KeyError:
                flat_before[top] = {}

    async with Scaffold(cfg, use_servers=True) as sf:
        await sf.server(init={"test": 2})
        c = await sf.client()
        await c.cmd(P("s.load"), str(fname))

        flat_after = {}
        for top in ("a", "zz", "new"):
            try:
                flat_after[top] = _flat(await _fetch(c, top))
            except KeyError:
                flat_after[top] = {}

    assert flat_before == flat_after, (flat_before, flat_after)
