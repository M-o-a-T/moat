# -*- coding: utf-8 -*-
"""
Test for SignalClient.update_profile
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
async def test_update_profile_ok():
    """
    Test successful SignalClient.update_profile.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "result": {},
            "id": "test_update_profile_ok",
        },
    )
    res = await SIGNAL_CLI.update_profile(
        given_name="Test",
        family_name="Test",
        about="Test",
    )
    assert isinstance(res, bool)
    assert res
    pook.reset()


@pytest.mark.anyio
@pook.activate
async def test_update_profile_error():
    """
    Test unsuccessful SignalClient.update_profile.
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
            "id": "test_update_profile_error",
        },
    )
    with pytest.raises(Exception) as exc_info:
        await SIGNAL_CLI.update_profile(
            given_name="Test",
            family_name="Test",
            about="Test",
            request_id="test_update_profile_error",
        )
    assert "Specified account does not exist" in str(exc_info.value)
    pook.reset()
