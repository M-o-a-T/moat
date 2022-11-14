# -*- coding: utf-8 -*-
"""
Test for SignalCliJSONRPCApi.version
"""


import pook
from packaging import version

#  pylint: disable=import-error
from pysignalclijsonrpc.api import SignalCliJSONRPCApi

SIGNAL_CLI = SignalCliJSONRPCApi(
    endpoint="http://mock.pook/api/v1/rpc",
    account="42",
)


@pook.activate
def test_version():
    """
    Test successful SignalCliJSONRPCApi.version.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "result": {"version": "0.11.5.1"},
            "id": "test_version",
        },
    )
    res = SIGNAL_CLI.version
    assert isinstance(res, str)
    assert version.parse(res) > version.parse("0.0.1")
    pook.reset()
