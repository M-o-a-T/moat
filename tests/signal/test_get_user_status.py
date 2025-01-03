"""
Test for SignalClient.get_user_status
"""

from __future__ import annotations

import pook
import pytest
from jmespath import search as j_search

#  pylint: disable=import-error
from moat.signal.api import SignalClient

SIGNAL_CLI = SignalClient(
    endpoint="http://mock.pook/api/v1/rpc",
    account="42",
)


@pytest.mark.anyio
@pook.activate
async def test_get_user_status_ok():
    """
    Test successful SignalClient.get_user_status.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "result": [
                {
                    "recipient": "+491337",
                    "number": "+491337",
                    "uuid": "1337-42-1337-42-1337",
                    "isRegistered": True,
                },
            ],
            "id": "test_get_user_status_ok",
        },
    )
    res = await SIGNAL_CLI.get_user_status(
        recipients=["+491337"],
    )
    assert j_search(
        "[?number == '+491337'].{isRegistered: isRegistered}",
        res,
    )
    assert res[0].get("isRegistered")
    pook.reset()


@pytest.mark.anyio
@pook.activate
async def test_get_user_status_error():
    """
    Test unsuccessful SignalClient.get_user_status.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "error": {
                "code": -32602,
                "message": "Specified account does not exist",
                "data": None,
            },
            "id": "test_get_user_status_error",
        },
    )
    with pytest.raises(Exception) as exc_info:
        await SIGNAL_CLI.get_user_status(
            recipients=["+491337"],
            request_id="test_get_user_status_error",
        )
    assert "Specified account does not exist" in str(exc_info.value)
    pook.reset()
