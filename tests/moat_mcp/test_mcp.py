"""End-to-end tests for the MoaT MCP server and its link service."""

from __future__ import annotations

import anyio
import json
import logging
import pytest

from mcp.server.fastmcp import FastMCP
from mcp.shared.memory import create_connected_server_and_client_session

from moat.util import attrdict
from moat.lib.path import P
from moat.link._test import Scaffold
from moat.mcp import load_service, services
from moat.mcp.link import LinkMCP, LinkService

pytestmark = pytest.mark.anyio


def test_load_service():
    "The link service is discoverable by name."
    assert load_service("link") is LinkService

    with pytest.raises(ValueError, match="nonesuch"):
        load_service("nonesuch")


async def test_link_backend(cfg):
    "The link backend reads/writes values and watches paths."
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
        anyio.create_task_group() as tg,
    ):
        mcp = LinkMCP(c, tg)
        assert await mcp.value_get("test.mcp.none") is None

        await mcp.value_set("test.mcp.v", 42)
        await c.i_sync()
        assert await mcp.value_get("test.mcp.v") == 42

        wid = await mcp.watch_start("test.mcp.w")
        assert await mcp.watch_get(wid) == []

        await mcp.value_set("test.mcp.w", 1)
        items = await mcp.watch_get(wid, timeout=2)
        assert len(items) == 1
        assert items[0]["value"] == 1
        assert items[0]["path"] == ["test", "mcp", "w"]
        assert items[0]["meta"] is not None

        with anyio.fail_after(2):
            assert await mcp.watch_get(wid, timeout=0.2) == []

        await mcp.watch_stop(wid)
        with pytest.raises(KeyError):
            await mcp.watch_get(wid)

        tg.cancel_scope.cancel()


async def test_watch_subtree(cfg):
    "A subtree watch reports the full path of each change."
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as c,
        anyio.create_task_group() as tg,
    ):
        mcp = LinkMCP(c, tg)
        wid = await mcp.watch_start("test.mcp.sub", subtree=True)

        await mcp.value_set("test.mcp.sub.a", 1)
        await mcp.value_set("test.mcp.sub.b.c", 2)

        seen: dict[tuple, object] = {}
        with anyio.fail_after(5):
            while len(seen) < 2:
                for item in await mcp.watch_get(wid, timeout=2):
                    seen[tuple(item["path"])] = item["value"]

        assert seen[("test", "mcp", "sub", "a")] == 1
        assert seen[("test", "mcp", "sub", "b", "c")] == 2

        await mcp.aclose()
        tg.cancel_scope.cancel()


async def test_mcp_client_session(cfg, monkeypatch):
    "Drive the full MCP server (with the link service) via a client session."

    # FastMCP reconfigures logging on construction; the test harness forbids
    # that, so neutralise it here.
    monkeypatch.setattr(logging, "basicConfig", lambda *a, **k: None)  # noqa: ARG005

    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        anyio.create_task_group() as tg,
    ):
        mcp_cfg = attrdict(services=attrdict(link=attrdict(link=sf.cfg)))
        async with services(mcp_cfg, tg) as svc:
            assert [s.name for s in svc] == ["link"]

            server = FastMCP("moat")
            for service in svc:
                await service.register(server)

            async with create_connected_server_and_client_session(server) as session:
                tools = {t.name for t in (await session.list_tools()).tools}
                assert {
                    "link_get_value",
                    "link_set_value",
                    "link_watch_start",
                    "link_watch_get",
                    "link_watch_stop",
                } <= tools

                await session.call_tool("link_set_value", {"path": "test.mcp.cli", "value": 7})
                with anyio.fail_after(5):
                    while True:
                        res = await session.call_tool("link_get_value", {"path": "test.mcp.cli"})
                        if res.content and json.loads(res.content[0].text) == 7:
                            break
                        await anyio.sleep(0.05)

        tg.cancel_scope.cancel()


def test_path_import():
    "P is importable (smoke test for the path helper used by the service)."
    assert list(P("a.b")) == ["a", "b"]
