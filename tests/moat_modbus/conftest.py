# pylint: disable=missing-module-docstring,missing-function-docstring  # noqa: D100
from __future__ import annotations
import pytest


@pytest.fixture
def anyio_backend():  # noqa: D103
    return "trio"
