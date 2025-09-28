from __future__ import annotations  # noqa: D100

import copy
import pytest

from moat.util import CFG, ensure_cfg

ensure_cfg("moat.link.server")


@pytest.fixture(autouse=True)
def reset_client_nr():  # noqa: D103
    from moat.link.server import _server as _s

    _s._client_nr = 0  # noqa: SLF001


@pytest.fixture
def anyio_backend():  # noqa: D103
    return "trio"


@pytest.fixture
def cfg():  # noqa: D103
    c = copy.deepcopy(CFG)
    return c
