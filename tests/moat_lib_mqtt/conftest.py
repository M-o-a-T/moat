"""Configuration for moat.lib.mqtt tests."""

from __future__ import annotations

import anyio
import pytest

from moat.util import attrdict
from moat.link._test import run_broker

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def mqtt_broker_addr() -> AsyncGenerator[str, None]:
    """
    Start a test MQTT broker and return the Unix socket path it's listening on.

    Uses the MQTT broker from moat.link._test (FlashMQ).
    """
    cfg = attrdict()
    async with anyio.create_task_group() as tg:
        sock_path = await tg.start(run_broker, cfg)
        try:
            yield sock_path
        finally:
            tg.cancel_scope.cancel()
