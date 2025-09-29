from __future__ import annotations  # noqa: D100

import pytest


@pytest.fixture
def anyio_backend():  # noqa: D103
    return "trio"
