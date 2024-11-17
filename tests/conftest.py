from __future__ import annotations

import copy
import pytest

from moat.link._test import CFG


@pytest.fixture
def anyio_backend():
    return "trio"


@pytest.fixture
def cfg():
    c = copy.deepcopy(CFG)
    return c
