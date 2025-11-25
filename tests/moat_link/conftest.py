# noqa:D100
from __future__ import annotations

import pytest

if False:

    @pytest.fixture
    def anyio_backend():
        "restrict anyio backend"
        return "trio"
