"""
Regression tests for the deleted-node sweeper (:meth:`Server._flush_deleted`).

Tracks moat-96q: the sweeper walked the *live* node tree while parking
in every subtree, so concurrent traffic (children appearing beneath a
branch whose container dict was being iterated) killed the whole server
with::

    RuntimeError: dictionary changed size during iteration
"""

from __future__ import annotations

import anyio
import pytest
import random
import time
from logging import getLogger

from moat.util import attrdict
from moat.link.meta import MsgMeta
from moat.link.node import Node
from moat.link.server._server import Server

from typing import Any

_logger = getLogger(__name__)


def _sweeper_stub(cfg_timeout: float) -> tuple[attrdict, Node]:
    """Assemble the minimal stand-in expected by ``Server._flush_deleted``.

    Args:
        cfg_timeout: Published as ``cfg.timeout.delete``.

    Returns:
        The stub attribute object and the freshly built root node.
    """
    root = Node()
    srv = attrdict(
        logger=_logger,
        data=root,
        cfg=attrdict(timeout=attrdict(delete=cfg_timeout)),
    )
    return srv, root


def _leaf(branch: Node, name: str, *, stamp: float, data: Any = ...) -> Node:
    """Attach a metadata-bearing leaf named *name* under *branch*.

    Args:
        branch: Parent node to extend.
        name: Child key to create.
        stamp: Timestamp recorded in the child's metadata.
        data: Payload for the child; omitted (no value) when not given.

    Returns:
        The freshly created child node.
    """
    child = branch.add_child(name)
    child._meta = MsgMeta(origin="test", timestamp=stamp)  # noqa: SLF001
    if data is not ...:
        child._data = data  # noqa: SLF001
    return child


def _has_key(branch: Node, name: str) -> bool:
    "Tell whether *branch* currently sports a child called *name*."
    return name in branch._sub  # noqa: SLF001


@pytest.mark.anyio
async def test_flush_deleted_survives_concurrent_growth() -> None:
    """Children appearing mid-walk must neither abort nor derail sweeps."""
    srv, root = _sweeper_stub(0.05)
    now = time.time()

    # The doomed limb is seeded FIRST: dict order puts it ahead of the
    # churning branches, so the first sweep reaches it swiftly despite
    # the ever-growing rest of the tree.
    doom_branch = root.add_child("doomed")
    _leaf(doom_branch, "corpse_a", stamp=now - 3600)
    _leaf(doom_branch, "corpse_b", stamp=now - 3600)

    stamp = time.time()
    hot_names = ("alpha", "beta")
    hot_mids = []
    for name in hot_names:
        mid = root.add_child(name)
        hot_mids.append(mid)
        for idx in range(3):
            _leaf(mid, f"h{idx}", stamp=stamp, data=idx)

    rnd = random.Random(99)
    keep_spawning = True
    made_children = 0

    async def churn_leaves() -> None:
        "Keep grafting new leaves onto the hot limbs."
        nonlocal made_children
        counter = 0
        while keep_spawning:
            counter += 1
            made_children += 1
            _leaf(
                rnd.choice(hot_mids),
                f"warm{counter}",
                stamp=time.time(),
                data=counter,
            )
            await anyio.sleep(0.02)

    async with anyio.create_task_group() as tg:
        await tg.start(Server._flush_deleted, srv)  # noqa: SLF001
        tg.start_soon(churn_leaves)
        await anyio.sleep(1.5)
        keep_spawning = False
        tg.cancel_scope.cancel()

    # The churning backbone survived intact …
    for mid_idx, name in enumerate(hot_names):
        mid = hot_mids[mid_idx]
        for idx in range(3):
            key = f"h{idx}"
            assert mid[key].data == idx, f"{name}.{key} lost its payload"
            assert mid[key].meta is not None, f"{name}.{key} lost its metadata"

    # … the churn actually happened (else this test proves nothing) …
    assert made_children > 20, "churn task barely ran; test is vacuous"

    # … and the corpse branch was properly reaped.
    assert not _has_key(doom_branch, "corpse_a")
    assert not _has_key(doom_branch, "corpse_b")


@pytest.mark.anyio
async def test_flush_deleted_fresh_live_node_not_pruned() -> None:
    """Live-but-young neighbours coexist with ripe tombstones each round."""
    srv, root = _sweeper_stub(0.1)
    stale_branch = root.add_child("holder")
    _leaf(stale_branch, "ancient", stamp=time.time() - 7200)
    _leaf(stale_branch, "sprout", stamp=time.time(), data="live")

    async with anyio.create_task_group() as tg:
        await tg.start(Server._flush_deleted, srv)  # noqa: SLF001
        await anyio.sleep(1.0)  # grant at least one full sweep
        tg.cancel_scope.cancel()

    sprout = stale_branch["sprout"]
    assert not _has_key(stale_branch, "ancient"), "stale tombstone dodged the reaper"
    assert sprout.data == "live", "fresh live node got harvested wrongly"
