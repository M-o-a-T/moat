# noqa:D100
from __future__ import annotations

import copy
import pytest

from moat.link._test import CFG

if False:

    @pytest.fixture()
    def anyio_backend():
        "restrict anyio backend"
        return "trio"


@pytest.fixture()
def cfg():
    "fixture for the static config"
    c = copy.deepcopy(CFG)
    return c
