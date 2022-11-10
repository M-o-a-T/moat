# -*- coding: utf-8 -*-
"""
Test for SignalCliJSONRPCApi.send_message
"""

import pook
import pytest

from pysignalclijsonrpc.api import SignalCliJSONRPCApi

SIGNAL_CLI = SignalCliJSONRPCApi(
    endpoint="http://mock.pook/api/v1/rpc",
    account="42",
)


@pook.activate
def test_send_message_ok_text():
    """
    Test successful SignalCliJSONRPCApi.send_message with plain text message.
    """
    #  pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "result": {
                "timestamp": 1,
                "results": [
                    {
                        "recipientAddress": {"uuid": "1337", "number": "+491337"},
                        "type": "SUCCESS",
                    }
                ],
            },
            "id": "test_send_message_ok_text",
        },
    )
    assert (
        SIGNAL_CLI.send_message(
            message="Test",
            recipients="+491337",
        )
        == 1
    )


@pook.activate
def test_send_message_error_text():
    """
    Test unsuccessful SignalCliJSONRPCApi.send_message with plain text message.
    """
    #  pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "error": {
                "code": -1,
                "message": "Failed to send message",
                "data": {
                    "response": {
                        "timestamp": 1,
                        "results": [
                            {
                                "recipientAddress": {"uuid": None, "number": "+491337"},
                                "type": "UNREGISTERED_FAILURE",
                            }
                        ],
                    }
                },
            },
            "id": "test_send_message_error_text",
        },
    )
    with pytest.raises(Exception) as exc_info:
        SIGNAL_CLI.send_message(
            message="Test",
            recipients="+491337",
            request_id="test_send_message_error_text",
        )
    assert "Failed to send message" in str(exc_info.value)
