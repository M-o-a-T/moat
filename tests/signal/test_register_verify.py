"""
Test for SignalClient.register
"""

from __future__ import annotations

import pook
import pytest

#  pylint: disable=import-error
from moat.signal.api import SignalClient

SIGNAL_CLI = SignalClient(
    endpoint="http://mock.pook/api/v1/rpc",
    account="42",
)


RESPONSE_JSON_OK = {
    "jsonrpc": "2.0",
    "result": {},
    "id": "test_register_verify_ok",
}


@pytest.mark.anyio
@pook.activate
async def test_register_ok():
    """
    Test successful SignalClient.register.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json=RESPONSE_JSON_OK,
    )
    res = await SIGNAL_CLI.register()
    assert isinstance(res, dict)
    assert not res
    pook.reset()


@pytest.mark.anyio
@pook.activate
async def test_register_error():
    """
    Test unsuccessful SignalClient.register.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "error": {
                "code": -32602,
                "message": "Method requires valid account parameter",
                "data": None,
            },
            "id": "test_register_error",
        },
    )
    with pytest.raises(Exception) as exc_info:
        await SIGNAL_CLI.register(
            request_id="test_register_error",
        )
    assert "Method requires valid account parameter" in str(exc_info.value)
    pook.reset()


@pytest.mark.anyio
@pook.activate
async def test_verify_ok():
    """
    Test successful SignalClient.verify.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json=RESPONSE_JSON_OK,
    )
    res = await SIGNAL_CLI.verify(
        verification_code="42",
    )
    assert isinstance(res, dict)
    assert not res
    pook.reset()


@pytest.mark.anyio
@pook.activate
async def test_verify_error():
    """
    Test unsuccessful SignalClient.verify.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "error": {
                "code": -3,
                "message": "Verify error: [403] Authorization failed!",
                "data": None,
            },
            "id": "test_verify_error",
        },
    )
    with pytest.raises(Exception) as exc_info:
        await SIGNAL_CLI.verify(
            verification_code="42",
            request_id="test_verify_error",
        )
    assert "Verify error: [403] Authorization failed!" in str(exc_info.value)
    pook.reset()
