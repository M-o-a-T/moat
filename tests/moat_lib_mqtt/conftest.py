"""Configuration for moat.lib.mqtt tests."""

from __future__ import annotations

import pytest
import anyio

from moat.link._test import run_broker
from moat.util import attrdict

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator


@pytest.fixture
async def mqtt_broker_port() -> AsyncGenerator[int, None]:
    """
    Start a test MQTT broker and return the port it's listening on.

    Uses the MQTT broker from moat.link._test (FlashMQ).
    """
    cfg = attrdict()
    async with anyio.create_task_group() as tg:
        port = await tg.start(run_broker, cfg)
        try:
            yield port
        finally:
            tg.cancel_scope.cancel()
