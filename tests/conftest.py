from __future__ import annotations  # noqa: D100

import pytest


@pytest.fixture(autouse=True, scope="session")
def anyio_backend():
    return "trio"

@pytest.fixture(autouse=True, scope="session")
def in_test(free_tcp_port_factory):
    """
    This fixture ensures that the configuration for moat-link clients
    does not access port 1883 and thus won't disturb / depend on a
    locally runnign MQTT server.
    """
    from moat.util import CFG, ensure_cfg  # noqa:PLC0415

    ensure_cfg("moat.link")

    def fix_for_testing(cfg):
        if "backend" in cfg.link and cfg.link.backend.get("port", 1883) == 1883:
            cfg.link.backend.port = free_tcp_port_factory()

    CFG.env.in_test = fix_for_testing
    fix_for_testing(CFG)

    try:
        yield
    finally:
        del CFG.env.in_test
