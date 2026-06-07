"""End-to-end tests for ``moat.link.job`` CLI commands.

Each test runs the full ``moat link job ...`` decorator stack through
:py:meth:`moat.link._test.Scaffold.run` and verifies the resulting
state in the MoaT-Link tree.
"""

from __future__ import annotations

import pytest
import time

import moat.link.job  # noqa:F401 - register cfg
from moat.lib.path import P
from moat.link._test import Scaffold

pytestmark = pytest.mark.anyio


async def test_set_get_delete(cfg):
    """Add, read, then delete a job record via the CLI."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.job.prefix
        sub = cfg.link.job.sub.group + P("default")

        # Create a job.
        await sf.run(
            "link job at foo set -c test.greet -t 0 -i greet -v who there",
        )
        await c.i_sync()

        stored = await c.d_get(prefix + sub + P("foo"))
        assert stored["code"] == P("test.greet")
        assert stored["info"] == "greet"
        assert stored["data"] == {"who": "there"}
        # target=0 means "now"; we passed "-t 0" so the entry should
        # have target set close to current time.
        assert stored["target"] is not None
        assert abs(stored["target"] - time.time()) < 5

        # Read it back via the CLI.
        r = await sf.run("link job at foo get")
        assert "test.greet" in r.stdout
        assert "there" in r.stdout

        # The 'path' subcommand prints both control and state paths.
        r = await sf.run("link job at foo path")
        assert "job.any.default.foo" in r.stdout
        assert "run.job.any.default.foo" in r.stdout

        # Delete it (force=true since we set a non-None target).
        await sf.run("link job at foo delete -f")
        await c.i_sync()
        with pytest.raises(KeyError):
            await c.d_get(prefix + sub + P("foo"))


async def test_set_with_copy(cfg):
    """``--copy`` clones an existing entry as a template."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.job.prefix
        sub = cfg.link.job.sub.group + P("default")

        # Create the original.
        await sf.run("link job at orig set -c test.greet -i original -v who alice")
        await c.i_sync()

        # Clone it under a new name.
        full_orig_path = prefix + sub + P("orig")
        await sf.run(
            ("link", "job", "at", "clone", "set", "-C", str(full_orig_path), "-v", "who", "bob"),
        )
        await c.i_sync()

        clone = await c.d_get(prefix + sub + P("clone"))
        assert clone["code"] == P("test.greet")
        # The cloned entry keeps the original's info but applies new vars.
        assert clone["info"] == "original"
        assert clone["data"]["who"] == "bob"


async def test_list_table(cfg):
    """The CLI ``list -t`` command produces one-line summaries."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        await sf.run("link job at one set -c code.one -t -")
        await sf.run("link job at two set -c code.two -t -")
        await c.i_sync()

        r = await sf.run("link job at : list -t")
        assert "one" in r.stdout
        assert "two" in r.stdout
        # We never started anything so each row is "-never-".
        assert r.stdout.count("-never-") == 2


async def test_info_lists_groups(cfg):
    """``info`` lists the groups (or hosts) below the current root."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        # Make sure two groups exist below the AnyRunner prefix.
        await sf.run("link job -g groupA at foo set -c x -t -")
        await sf.run("link job -g groupB at bar set -c x -t -")
        await c.i_sync()

        r = await sf.run("link job info")
        assert "groupA" in r.stdout
        assert "groupB" in r.stdout


async def test_node_modes_use_distinct_paths(cfg):
    """``-n NODE`` selects single-node layout; ``-n -`` selects all-nodes layout."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
    ):
        prefix = cfg.link.job.prefix
        sub_grp = cfg.link.job.sub.group + P("default")
        sub_at = cfg.link.job.sub.single + P("node1") + P("default")
        sub_all = cfg.link.job.sub["all"] + P("default")

        await sf.run("link job at any_foo set -c x -t -")
        await sf.run("link job -n node1 at single_foo set -c x -t -")
        await sf.run("link job -n - at all_foo set -c x -t -")
        await c.i_sync()

        assert (await c.d_get(prefix + sub_grp + P("any_foo")))["code"] == P("x")
        assert (await c.d_get(prefix + sub_at + P("single_foo")))["code"] == P("x")
        assert (await c.d_get(prefix + sub_all + P("all_foo")))["code"] == P("x")
