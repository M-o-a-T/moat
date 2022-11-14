# -*- coding: utf-8 -*-
"""
Test for SignalCliJSONRPCApi.register
"""


import pook
import pytest

#  pylint: disable=import-error
from pysignalclijsonrpc.api import SignalCliJSONRPCApi

SIGNAL_CLI = SignalCliJSONRPCApi(
    endpoint="http://mock.pook/api/v1/rpc",
    account="42",
)


RESPONSE_JSON_OK = {
    "jsonrpc": "2.0",
    "result": {},
    "id": "test_register_verify_ok",
}


@pook.activate
def test_register_ok():
    """
    Test successful SignalCliJSONRPCApi.register.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json=RESPONSE_JSON_OK,
    )
    res = SIGNAL_CLI.register()
    assert isinstance(res, dict)
    assert not res
    pook.reset()


@pook.activate
def test_register_error():
    """
    Test unsuccessful SignalCliJSONRPCApi.register.
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
        SIGNAL_CLI.register(
            request_id="test_register_error",
        )
    assert "Method requires valid account parameter" in str(exc_info.value)
    pook.reset()


@pook.activate
def test_verify_ok():
    """
    Test successful SignalCliJSONRPCApi.verify.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json=RESPONSE_JSON_OK,
    )
    res = SIGNAL_CLI.verify(
        verification_code="42",
    )
    assert isinstance(res, dict)
    assert not res
    pook.reset()


@pook.activate
def test_verify_error():
    """
    Test unsuccessful SignalCliJSONRPCApi.verify.
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
        SIGNAL_CLI.verify(
            verification_code="42",
            request_id="test_verify_error",
        )
    assert "Verify error: [403] Authorization failed!" in str(exc_info.value)
    pook.reset()
