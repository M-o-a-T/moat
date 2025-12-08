from __future__ import annotations  # noqa: D100

import pytest


@pytest.fixture(autouse=True)
def reset_client_nr():  # noqa: D103
    from moat.link.server import _server as _s  # noqa: PLC0415

    _s._client_nr = 0  # noqa: SLF001


@pytest.fixture
def anyio_backend():  # noqa: D103
    return "trio"
