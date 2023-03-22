# pylint: disable=missing-module-docstring,missing-function-docstring
import pytest


@pytest.fixture
def anyio_backend():
    return "trio"
