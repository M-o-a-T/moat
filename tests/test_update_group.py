# -*- coding: utf-8 -*-
"""
Test for SignalClient.update_group
"""


import pook
import pytest

#  pylint: disable=import-error
from moat.signal.api import SignalClient

SIGNAL_CLI = SignalClient(
    endpoint="http://mock.pook/api/v1/rpc",
    account="42",
)


@pook.activate
def test_update_group_ok():
    """
    Test successful SignalClient.update_group.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "result": {
                "groupId": "1337",
                "results": [],
                "timestamp": 1,
            },
            "id": "test_update_group_ok",
        },
    )
    assert (
        SIGNAL_CLI.update_group(
            name="TEST",
            members=["+491337"],
        )
        == "1337"
    )
    pook.reset()


@pook.activate
def test_update_group_error():
    """
    Test unsuccessful SignalClient.update_group.
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
            "id": "test_update_group_error",
        },
    )
    with pytest.raises(Exception) as exc_info:
        SIGNAL_CLI.update_group(
            name="TEST",
            members=["+491337"],
            request_id="test_update_group_error",
        )
    assert "Specified account does not exist" in str(exc_info.value)
    pook.reset()
