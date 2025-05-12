# pylint: disable=missing-module-docstring,missing-function-docstring
from __future__ import annotations
import pytest


@pytest.fixture()
def anyio_backend():
    return "trio"
