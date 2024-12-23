# -*- coding: utf-8 -*-
"""
Test for SignalClient.join_group
"""

import pook
import pytest

#  pylint: disable=import-error
from moat.signal.api import SignalClient

SIGNAL_CLI = SignalClient(
    endpoint="http://mock.pook/api/v1/rpc",
    account="42",
)


@pytest.mark.anyio
@pook.activate
async def test_join_group_ok():
    """
    Test successful SignalClient.join_group.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "result": {
                "groupId": "1337",
                "timestamp": 1,
                "results": [
                    {
                        "recipientAddress": {"uuid": "42", "number": "+491337"},
                        "type": "SUCCESS",
                    }
                ],
            },
            "id": "test_join_group_ok",
        },
    )
    res = await SIGNAL_CLI.join_group(
        uri="1337",
    )
    assert res.get("groupId") == "1337"
    pook.reset()


@pytest.mark.anyio
@pook.activate
async def test_join_group_error():
    """
    Test unsuccessful SignalClient.join_group.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "error": {
                "code": -1,
                "message": "Group link is invalid: ...",
                "data": None,
            },
            "id": "test_join_group_error",
        },
    )
    with pytest.raises(Exception) as exc_info:
        await SIGNAL_CLI.join_group(
            uri="1337",
            request_id="test_join_group_error",
        )
    assert "Group link is invalid" in str(exc_info.value)
    pook.reset()
