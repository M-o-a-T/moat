"basic client tests"

from __future__ import annotations

import anyio
import logging
import pytest
import time

from jsonschema.exceptions import ValidationError

from moat.lib.path import P, Path
from moat.link._test import Scaffold
from moat.link.client import LinkSender
from moat.link.meta import MsgMeta


@pytest.mark.anyio
async def test_simple(cfg):
    "simple client-to-client comm test"
    async with Scaffold(cfg, use_servers=False) as sf:

        async def cl(*, task_status):
            c = await sf.client()

            async with c.monitor(P("test.here")) as mon:
                evt = anyio.Event()
                task_status.started(evt)
                async for m in mon:
                    assert m.data == "Hello"
                    assert m.meta.origin == "me!"
                    t = time.time()
                    assert t - 1 < m.meta.timestamp < t
                    evt.set()
                    break

        evt = await sf.tg.start(cl)
        c = await sf.client()
        om = MsgMeta(origin="me!")
        await c.send(P("test.here"), "Hello", meta=om, retain=True)
        with anyio.fail_after(1):
            await evt.wait()


class _DummyLink:
    def __init__(self, *, has_server: bool):
        self.name = "T"
        self.logger = logging.getLogger("tests.moat_link.test_client")
        self.announced = set()
        self.current_server = object() if has_server else None


def _mk_sender(*, has_server: bool):
    sender = LinkSender(_DummyLink(has_server=has_server))
    sent = []

    async def _send(path, *, data, meta, retain):
        sent.append((path, data, meta, retain))

    sender.send = _send
    return sender, sent


def _empty_root() -> Path:
    return Path()


@pytest.mark.anyio
async def test_d_set_verify_rejects_invalid(monkeypatch):
    "Strict schema verification rejects invalid payloads."
    monkeypatch.setattr("moat.link.client.Root.get", _empty_root)
    sender, sent = _mk_sender(has_server=True)

    async def _search(path, meta=False):  # noqa: ARG001
        return {"type": "integer"}

    sender.d_search = _search

    with pytest.raises(ValidationError):
        await sender.d_set(P("test.value"), "x", verify=True)
    assert sent == []


@pytest.mark.anyio
async def test_d_set_verify_warning_writes(caplog, monkeypatch):
    "Warning mode logs and writes invalid payloads."
    monkeypatch.setattr("moat.link.client.Root.get", _empty_root)
    sender, sent = _mk_sender(has_server=True)

    async def _search(path, meta=False):  # noqa: ARG001
        return {"type": "integer"}

    sender.d_search = _search
    with caplog.at_level(logging.WARNING):
        assert (await sender.d_set(P("test.value"), "x", verify=None)) is True
    assert len(sent) == 1
    assert any("Schema validation failed" in rec.message for rec in caplog.records)


@pytest.mark.anyio
async def test_d_set_verify_auto_when_server_present(monkeypatch):
    "Default verification is active under pytest when a server link exists."
    monkeypatch.setattr("moat.link.client.Root.get", _empty_root)
    sender, sent = _mk_sender(has_server=True)

    async def _search(path, meta=False):  # noqa: ARG001
        return {"type": "integer"}

    sender.d_search = _search

    with pytest.raises(ValidationError):
        await sender.d_set(P("test.value"), "x")
    assert sent == []


@pytest.mark.anyio
async def test_d_set_verify_auto_without_server(monkeypatch):
    "Default verification does not run without a server connection."
    monkeypatch.setattr("moat.link.client.Root.get", _empty_root)
    sender, sent = _mk_sender(has_server=False)

    async def _search(path, meta=False):  # noqa: ARG001
        raise AssertionError("schema lookup must not run")

    sender.d_search = _search

    assert (await sender.d_set(P("test.value"), "x")) is True
    assert len(sent) == 1


@pytest.mark.anyio
async def test_d_set_verify_missing_schema(monkeypatch):
    "Missing schema entries are ignored."
    monkeypatch.setattr("moat.link.client.Root.get", _empty_root)
    sender, sent = _mk_sender(has_server=True)

    async def _search(path, meta=False):  # noqa: ARG001
        raise KeyError(path)

    sender.d_search = _search

    assert (await sender.d_set(P("test.value"), "x", verify=True)) is True
    assert len(sent) == 1
