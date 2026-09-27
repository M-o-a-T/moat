"""
Fixtures for the heat controller tests.
"""

from __future__ import annotations

import pytest

from moat.link._test import Scaffold

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.link.client import LinkSender

    from collections.abc import AsyncIterator


@pytest.fixture
async def heat_scaffold(cfg) -> AsyncIterator[Scaffold]:
    "a MoaT-Link test server"
    async with Scaffold(cfg, use_servers=True) as sf, sf.server_(init={}):
        yield sf


@pytest.fixture
async def link(heat_scaffold: Scaffold) -> AsyncIterator[LinkSender]:
    "a client of the test server"
    async with heat_scaffold.client_() as c:
        yield c
