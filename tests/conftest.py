from __future__ import annotations  # noqa: D100

import copy
import pytest

from moat.lib import config
from moat.lib.config import CFG

config.TEST = True


@pytest.fixture(autouse=True, scope="session")
def anyio_backend():
    "never use asyncio for testing"
    return "trio"


@pytest.fixture(autouse=True, scope="session")
def in_test(free_tcp_port_factory):
    """
    This fixture ensures that the configuration for moat-link clients
    does not access port 1883 and thus won't disturb / depend on a
    locally runnign MQTT server.
    """
    from moat.lib.config import CFG  # noqa:PLC0415

    def fix_for_testing(cfg):
        if "backend" in cfg.link and cfg.link.backend.get("port", 1883) == 1883:
            cfg.link.backend.port = free_tcp_port_factory()

    CFG.env.in_test = fix_for_testing
    try:
        fix_for_testing(CFG)
    except AttributeError:
        pass

    try:
        yield
    finally:
        del CFG.env.in_test


@pytest.fixture
def cfg():
    "fixture for the static config"
    with CFG.with_config(config.CfgStore()) as c:
        yield copy.deepcopy(c.result.moat)
