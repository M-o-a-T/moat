"""
Test for SignalClient.quit_group
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


@pytest.mark.anyio
@pook.activate
async def test_quit_group_ok():
    """
    Test successful SignalClient.quit_group.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "result": {"timestamp": 1, "results": []},
            "id": "test_quit_group_ok",
        },
    )
    assert (
        await SIGNAL_CLI.quit_group(
            groupid="1337",
        )
    ).get("timestamp") == 1
    pook.reset()


@pytest.mark.anyio
@pook.activate
async def test_quit_group_error():
    """
    Test unsuccessful SignalClient.quit_group.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json={
            "jsonrpc": "2.0",
            "error": {
                "code": -1,
                "message": "Invalid group id: Failed to decode groupId (must be base64) ...",
                "data": None,
            },
            "id": "test_quit_group_error",
        },
    )
    with pytest.raises(Exception) as exc_info:
        await SIGNAL_CLI.quit_group(
            groupid="1337",
            request_id="test_quit_group_error",
        )
    assert "Invalid group id" in str(exc_info.value)
    pook.reset()
