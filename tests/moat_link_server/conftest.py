from __future__ import annotations

import copy
import pytest

from moat.util import CFG, ensure_cfg

ensure_cfg("moat.link.server")

@pytest.fixture(autouse=True)
def reset_client_nr():
    from moat.link.server import _server as _s
    _s._client_nr = 0


@pytest.fixture()
def anyio_backend():
    return "trio"


@pytest.fixture()
def cfg():
    c = copy.deepcopy(CFG)
    return c
