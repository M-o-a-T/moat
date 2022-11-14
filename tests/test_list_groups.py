# -*- coding: utf-8 -*-
"""
Test for SignalCliJSONRPCApi.list_groups
"""


import pook
import pytest

#  pylint: disable=import-error
from pysignalclijsonrpc.api import SignalCliJSONRPCApi

SIGNAL_CLI = SignalCliJSONRPCApi(
    endpoint="http://mock.pook/api/v1/rpc",
    account="42",
)


RESPONSE_JSON = {
    "jsonrpc": "2.0",
    "result": [
        {
            "id": "1",
            "name": "Test 1",
            "description": "",
            "isMember": True,
            "isBlocked": False,
            "messageExpirationTime": 604800,
            "members": [
                {"number": "+491337", "uuid": "1337"},
                {
                    "number": "+4942",
                    "uuid": "42",
                },
            ],
            "pendingMembers": [],
            "requestingMembers": [],
            "admins": [
                {"number": "+491337", "uuid": "1337"},
            ],
            "banned": [],
            "permissionAddMember": "EVERY_MEMBER",
            "permissionEditDetails": "EVERY_MEMBER",
            "permissionSendMessage": "EVERY_MEMBER",
            "groupInviteLink": None,
        },
        {
            "id": "2",
            "name": "Test 2",
            "description": "",
            "isMember": True,
            "isBlocked": False,
            "messageExpirationTime": 604800,
            "members": [
                {"number": "+491337", "uuid": "1337"},
            ],
            "pendingMembers": [],
            "requestingMembers": [],
            "admins": [
                {
                    "number": "+4915127115406",
                    "uuid": "f373e846-3781-45a8-8533-433e4bb430f7",
                }
            ],
            "banned": [],
            "permissionAddMember": "EVERY_MEMBER",
            "permissionEditDetails": "EVERY_MEMBER",
            "permissionSendMessage": "EVERY_MEMBER",
            "groupInviteLink": None,
        },
    ],
    "id": "test_list_groups_ok",
}


@pook.activate
def test_list_groups_ok():
    """
    Test successful SignalCliJSONRPCApi.list_groups.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json=RESPONSE_JSON,
    )
    res = SIGNAL_CLI.list_groups()
    assert isinstance(res, list)
    assert isinstance(res[0], dict)
    assert len(res) == 2
    pook.reset()


@pook.activate
def test_get_group_ok():
    """
    Test successful SignalCliJSONRPCApi.get_group.
    """
    # pylint: disable=protected-access
    pook.post(
        SIGNAL_CLI._endpoint,
        reply="200",
        response_json=RESPONSE_JSON,
    )
    res = SIGNAL_CLI.get_group(
        groupid="1",
    )
    assert isinstance(res, list)
    assert isinstance(res[0], dict)
    assert len(res) == 1
    pook.reset()


@pook.activate
def test_list_groups_error():
    """
    Test unsuccessful SignalCliJSONRPCApi.list_groups.
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
            "id": "test_list_groups_error",
        },
    )
    with pytest.raises(Exception) as exc_info:
        SIGNAL_CLI.list_groups(
            request_id="test_list_groups_error",
        )
    assert "Specified account does not exist" in str(exc_info.value)
    pook.reset()
