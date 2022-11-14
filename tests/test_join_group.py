# -*- coding: utf-8 -*-
"""
Test for SignalCliJSONRPCApi.join_group
"""


import pook
import pytest

#  pylint: disable=import-error
from pysignalclijsonrpc.api import SignalCliJSONRPCApi

SIGNAL_CLI = SignalCliJSONRPCApi(
    endpoint="http://mock.pook/api/v1/rpc",
    account="42",
)


@pook.activate
def test_join_group_ok():
    """
    Test successful SignalCliJSONRPCApi.join_group.
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
    res = SIGNAL_CLI.join_group(
        uri="1337",
    )
    assert res.get("groupId") == "1337"
    pook.reset()


@pook.activate
def test_join_group_error():
    """
    Test unsuccessful SignalCliJSONRPCApi.join_group.
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
        SIGNAL_CLI.join_group(
            uri="1337",
            request_id="test_join_group_error",
        )
    assert "Group link is invalid" in str(exc_info.value)
    pook.reset()
