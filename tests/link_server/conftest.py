from __future__ import annotations

import copy
import pytest

from moat.util import yload, merge, CFG, ensure_cfg

ensure_cfg("moat.link.server")


@pytest.fixture
def anyio_backend():
    return "trio"


@pytest.fixture
def cfg():
    c = copy.deepcopy(CFG)
    return c
