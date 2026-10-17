"""Tests for ``moat dev followme``: scan polling with notifications.

The SafeQ backend is faked by monkeypatching the module's API helpers, so
these tests exercise the CLI plumbing (including the MoaT-Link
notification path) without network access.
"""

from __future__ import annotations

import anyio
import base64
import json
import pytest
import time

from moat.util import NotGiven
from moat.lib.path import P
from moat.link._test import Scaffold

pytestmark = pytest.mark.anyio

FAKE_DOCS = [
    {
        "Guid": "g1",
        "FileName": "scan-one.pdf",
        "FileSizeBytes": 1234,
        "Date": "2026-10-14T07:00:00",
        "PageCount": 1,
    },
    {
        "Guid": "g2",
        "FileName": "scan-two.pdf",
        "FileSizeBytes": 4321,
        "Date": "2026-10-14T07:01:00",
        "PageCount": 2,
    },
]


def _fake_jwt() -> str:
    """A structurally valid, unexpired JWT."""

    def enc(data: dict) -> str:
        return base64.urlsafe_b64encode(json.dumps(data).encode()).rstrip(b"=").decode()

    now = int(time.time())
    return f"{enc({'alg': 'HS256'})}.{enc({'exp': now + 3600, 'nbf': now - 10})}.sig"


@pytest.fixture
def fmp_fake(monkeypatch):
    """Replace the SafeQ HTTP API with canned responses."""
    from moat.dev.followme import _main as fm  # noqa: PLC0415

    async def fake_backend(client, page_url):  # noqa: ARG001
        return fm.Backend(auth_url="http://auth", image_url="http://img", raw_cfg={})

    async def fake_list(client, image_url, token):  # noqa: ARG001
        return [dict(d) for d in FAKE_DOCS]

    async def fake_download(client, image_url, token, guid, dest):  # noqa: ARG001
        doc = next(d for d in FAKE_DOCS if d["Guid"] == guid)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(b"x" * doc["FileSizeBytes"])
        return doc["FileSizeBytes"]

    async def fake_delete(client, image_url, token, guid):  # noqa: ARG001
        return None

    monkeypatch.setattr(fm, "discover_backend", fake_backend)
    monkeypatch.setattr(fm, "api_list_scans", fake_list)
    monkeypatch.setattr(fm, "api_download_one", fake_download)
    monkeypatch.setattr(fm, "api_delete_one", fake_delete)


async def _get_notify(reader, path: str, timeout: float = 5) -> dict:
    """Fetch a notification, retrying until the server has it."""
    with anyio.fail_after(timeout):
        while True:
            try:
                data = await reader.d_get(P(path))
            except (KeyError, ValueError):
                data = NotGiven
            if data is not NotGiven:
                return data
            await anyio.sleep(0.05)


async def _run_poll(sf: Scaffold, *extra: str) -> None:
    """Run one polling round with notifications enabled."""
    await sf.run(
        "dev",
        "followme",
        "--token",
        _fake_jwt(),
        "poll",
        "--rounds",
        "1",
        "--interval",
        "0.1",
        "--notify",
        *extra,
        do_stdout=False,
    )


async def test_poll_notify_single(cfg, fmp_fake, tmp_path):  # noqa: ARG001
    """Each downloaded document produces its own notification."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as reader,
    ):
        await _run_poll(sf, "--download", str(tmp_path))

        start = await _get_notify(reader, "notify.scan.poll")
        assert start["title"] == "Scan polling started"

        one = await _get_notify(reader, "notify.scan.doc.g1")
        assert one["name"] == "scan-one.pdf"
        assert one["size"] == 1234
        two = await _get_notify(reader, "notify.scan.doc.g2")
        assert two["name"] == "scan-two.pdf"
        assert two["size"] == 4321


async def test_poll_notify_summary(cfg, fmp_fake, tmp_path):  # noqa: ARG001
    """Multiple documents produce one summary notification."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as reader,
    ):
        await _run_poll(sf, "--download", str(tmp_path), "--notify-mode", "summary")

        start = await _get_notify(reader, "notify.scan.poll")
        assert start["title"] == "Scan polling started"

        summ = await _get_notify(reader, "notify.scan.docs")
        assert summ["count"] == 2
        assert summ["size"] == 1234 + 4321
        assert summ["names"] == ["scan-one.pdf", "scan-two.pdf"]


async def test_poll_no_notify(cfg, fmp_fake, tmp_path):  # noqa: ARG001
    """Without --notify, nothing is written to the notify subtree."""
    async with (
        Scaffold(cfg, use_servers=True) as sf,
        sf.server_(init={"Hello": "there!"}),
        sf.client_() as reader,
    ):
        await sf.run(
            "dev",
            "followme",
            "--token",
            _fake_jwt(),
            "poll",
            "--rounds",
            "1",
            "--download",
            str(tmp_path),
            do_stdout=False,
        )
        with pytest.raises(KeyError):
            await reader.d_get(P("notify.scan.poll"))
