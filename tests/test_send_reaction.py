# -*- coding: utf-8 -*-
"""
Test for SignalCliJSONRPCApi.send_reaction
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
def test_send_reaction_ok():
    """
    Test successful SignalCliJSONRPCApi.send_reaction.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "result": {
                "timestamp": 1,
                "results": [
                    {
                        "recipientAddress": {"uuid": "42", "number": "+491337"},
                        "type": "SUCCESS",
                    }
                ],
            },
            "id": "test_send_reaction_ok",
        },
    )
    res = SIGNAL_CLI.send_reaction(
        recipient="+491337",
        emoji="✅",
        target_author="+4942",
        target_timestamp=2,
    )
    assert isinstance(res, int)
    assert res == 1
    pook.reset()


@pook.activate
def test_send_reaction_error():
    """
    Test unsuccessful SignalCliJSONRPCApi.send_reaction.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "error": {
                "code": -1,
                "message": "The user +4942 is not registered.",
                "data": None,
            },
            "id": "test_send_reaction_error",
        },
    )
    with pytest.raises(Exception) as exc_info:
        SIGNAL_CLI.send_reaction(
            recipient="+491337",
            emoji="✅",
            target_author="+4942",
            target_timestamp=2,
            request_id="test_send_reaction_error",
        )
    assert "The user +4942 is not registered." in str(exc_info.value)
    pook.reset()
