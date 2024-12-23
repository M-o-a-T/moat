# -*- coding: utf-8 -*-
"""
Test for SignalClient.send_message
"""

import os
from base64 import b64decode
from tempfile import mkstemp

import pook
import pytest
from test_list_groups import RESPONSE_JSON as TEST_LIST_GROUPS_RESPONSE_JSON

#  pylint: disable=import-error
from moat.signal.api import SignalClient

SIGNAL_CLI = SignalClient(
    endpoint="http://mock.pook/api/v1/rpc",
    account="42",
)
# pylint: disable=line-too-long
IMAGE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg=="
IMAGE_BYTEARRAY = bytearray(b64decode(IMAGE))


@pook.activate
async def _send_message_ok(
    recipients: list = None,
    message: str = "",
    mention: str = "",
    attachments_as_files: list = None,
    attachments_as_bytes: list = None,
    cleanup_attachments: bool = False,
    group_id: str = "",
):  # pylint: disable=unused-argument,too-many-arguments
    """
    Test successful SignalClient.send_message with params.
    """
    recipients = recipients or ["+491337"]
    response_json = {
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
        "id": "test_send_message_ok",
    }
    if group_id:
        response_json["result"]["results"][0]["groupId"] = group_id
    with pook.use():
        # pylint: disable=protected-access
        pook.post(
            SIGNAL_CLI._endpoint,
            body=pook.regex('"getUserStatus"'),
            reply="200",
            response_json={
                "jsonrpc": "2.0",
                "result": [
                    {
                        "recipient": recipients[0],
                        "number": "+491337",
                        "uuid": "1337-42-1337-42-1337",
                        "isRegistered": True,
                    }
                ],
                "id": "test_get_user_status_ok",
            },
        )
        # pylint: disable=protected-access
        pook.post(
            SIGNAL_CLI._endpoint,
            body=pook.regex('"listGroups"'),
            reply="200",
            response_json=TEST_LIST_GROUPS_RESPONSE_JSON,
        )
        # pylint: disable=protected-access
        pook.post(
            SIGNAL_CLI._endpoint,
            body=pook.regex('"send"'),
            reply="200",
            response_json=response_json,
        )
        res = await SIGNAL_CLI.send_message(
            message=message,
            recipients=recipients,
            attachments_as_files=attachments_as_files,
            attachments_as_bytes=attachments_as_bytes,
            cleanup_attachments=cleanup_attachments,
            request_id="test_send_message_ok",
        )
        assert res.get("timestamps").get(1).get("recipients") == recipients
    pook.reset()


@pook.activate
async def _send_message_error(
    recipients: list = None,
    message: str = "",
    mention: str = "",
    attachments_as_files: list = None,
    attachments_as_bytes: list = None,
    cleanup_attachments: bool = False,
    **kwargs,
):  # pylint: disable=unused-argument,too-many-arguments
    """
    Test unsuccessful SignalClient.send_message with params.
    """
    recipients = recipients or ["+491337"]
    with pytest.raises(Exception) as exc_info:
        with pook.use():
            # pylint: disable=protected-access
            pook.post(
                SIGNAL_CLI._endpoint,
                body=pook.regex('"getUserStatus"'),
                reply="200",
                response_json={
                    "jsonrpc": "2.0",
                    "result": [
                        {
                            "recipient": recipients[0],
                            "number": "+491337",
                            "uuid": "1337-42-1337-42-1337",
                            "isRegistered": True,
                        }
                    ],
                    "id": "test_get_user_status_ok",
                },
            )
            # pylint: disable=protected-access
            pook.post(
                SIGNAL_CLI._endpoint,
                body=pook.regex('"listGroups"'),
                reply="200",
                response_json=TEST_LIST_GROUPS_RESPONSE_JSON,
            )
            #  pylint: disable=protected-access
            pook.post(
                SIGNAL_CLI._endpoint,
                body=pook.regex('"send"'),
                reply="200",
                response_json={
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -1,
                        "message": kwargs.get("exception", "Failed to send message"),
                        "data": None,
                    },
                    "id": "test_send_message_error",
                },
            )
            await SIGNAL_CLI.send_message(
                message=message,
                recipients=recipients,
                attachments_as_files=attachments_as_files,
                attachments_as_bytes=attachments_as_bytes,
                cleanup_attachments=cleanup_attachments,
                request_id="test_send_message_error",
            )
            assert kwargs.get("exception", "Failed to send message") in str(exc_info.value)
    pook.reset()


@pytest.mark.anyio
async def test_send_message_ok_text_group():
    """
    Test successful SignalClient.send_message to group with plain text message.
    """
    await _send_message_ok(message="Test", group_id="aabbcc")


@pytest.mark.anyio
async def test_send_message_error_text_group():
    """
    Test unsuccessful SignalClient.send_message to group with plain text message.
    """
    await _send_message_error(message="Test", group_id="aabbcc")


@pytest.mark.anyio
async def test_send_message_ok_text():
    """
    Test successful SignalClient.send_message with plain text message.
    """
    await _send_message_ok(message="Test")


@pytest.mark.anyio
async def test_send_message_error_text():
    """
    Test unsuccessful SignalClient.send_message with plain text message.
    """
    await _send_message_error(message="Test")


@pytest.mark.anyio
async def test_send_message_ok_text_mention():
    """
    Test successful SignalClient.send_message with plain text message and mention.
    """
    await _send_message_ok(message="Test", mention="0:0:+491337")


@pytest.mark.anyio
async def test_send_message_error_text_mention():
    """
    Test unsuccessful SignalClient.send_message with plain text message and mention.
    """
    await _send_message_error(
        message="Test",
        mention="0:0:+491337",
        exception="Invalid mention syntax",
    )


@pytest.mark.anyio
async def _send_message_ok_attachments_as_files(**kwargs):
    """
    Test successful SignalClient.send_message with attachments_as_files and params.
    """
    _, filename = mkstemp(suffix="png")
    with open(filename, "wb") as f_h:
        f_h.write(b64decode(IMAGE))
    await _send_message_ok(attachments_as_files=[filename], **kwargs)
    return filename


@pytest.mark.anyio
async def test_send_message_ok_attachments_as_files_keep():
    """
    Test successful SignalClient.send_message with attachments_as_files and keep files.
    """
    filename = await _send_message_ok_attachments_as_files()
    assert os.path.exists(filename)


@pytest.mark.anyio
async def test_send_message_ok_attachments_as_files_cleanup():
    """
    Test successful SignalClient.send_message with attachments_as_files and cleanup files.
    """
    filename = await _send_message_ok_attachments_as_files(cleanup_attachments=True)
    assert not os.path.exists(filename)


@pytest.mark.anyio
async def test_send_message_error_attachments_as_files():
    """
    Test unsuccessful SignalClient.send_message with attachments_as_files.
    """
    await _send_message_error(attachments_as_files=["/foo/bar.gif"], exception="FileNotFoundError")


@pytest.mark.anyio
async def test_send_message_ok_attachments_as_bytes():
    """
    Test successful SignalClient.send_message with attachments_as_bytes.
    """
    await _send_message_ok(attachments_as_bytes=[IMAGE_BYTEARRAY])


@pytest.mark.anyio
async def test_send_message_error_attachments_as_bytes():
    """
    Test unsuccessful SignalClient.send_message with attachments_as_bytes.
    """
    await _send_message_error(attachments_as_bytes=[IMAGE_BYTEARRAY])
