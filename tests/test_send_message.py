# -*- coding: utf-8 -*-
"""
Test for SignalCliJSONRPCApi.send_message
"""

import os
from base64 import b64decode
from tempfile import mkstemp

import pook
import pytest

#  pylint: disable=import-error
from pysignalclijsonrpc.api import SignalCliJSONRPCApi

SIGNAL_CLI = SignalCliJSONRPCApi(
    endpoint="http://mock.pook/api/v1/rpc",
    account="42",
)
#  pylint: disable=line-too-long
IMAGE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg=="
IMAGE_BYTEARRAY = bytearray(b64decode(IMAGE))


@pook.activate
def _send_message_ok(
    message: str = "",
    filenames: list = None,
    attachments_as_bytes: list = None,
    cleanup_filenames: bool = False,
):
    """
    Test successful SignalCliJSONRPCApi.send_message with params.
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
            "id": "test_send_message_ok",
        },
    )
    assert (
        SIGNAL_CLI.send_message(
            message=message,
            recipients="+491337",
            filenames=filenames,
            attachments_as_bytes=attachments_as_bytes,
            cleanup_filenames=cleanup_filenames,
        )
        == 1
    )
    pook.reset()


@pook.activate
def _send_message_error(
    message: str = "",
    filenames: list = None,
    attachments_as_bytes: list = None,
    cleanup_filenames: bool = False,
    **kwargs,
):
    """
    Test unsuccessful SignalCliJSONRPCApi.send_message with params.
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
            "id": "test_send_message_error",
        },
    )
    with pytest.raises(Exception) as exc_info:
        SIGNAL_CLI.send_message(
            message=message,
            recipients="+491337",
            filenames=filenames,
            attachments_as_bytes=attachments_as_bytes,
            cleanup_filenames=cleanup_filenames,
            request_id="test_send_message_error",
        )
    assert kwargs.get("exception", "Failed to send message") in str(exc_info.value)
    pook.reset()


def test_send_message_ok_text():
    """
    Test successful SignalCliJSONRPCApi.send_message with plain text message.
    """
    _send_message_ok(message="Test")


def test_send_message_error_text():
    """
    Test unsuccessful SignalCliJSONRPCApi.send_message with plain text message.
    """
    _send_message_error(message="Test")


def _send_message_ok_filenames(**kwargs):
    """
    Test successful SignalCliJSONRPCApi.send_message with filenames and params.
    """
    _, filename = mkstemp(suffix="png")
    with open(filename, "wb") as f_h:
        f_h.write(b64decode(IMAGE))
    _send_message_ok(filenames=[filename], **kwargs)
    return filename


def test_send_message_ok_filenames_keep():
    """
    Test successful SignalCliJSONRPCApi.send_message with filenames and keep files.
    """
    filename = _send_message_ok_filenames()
    assert os.path.exists(filename)


def test_send_message_ok_filenames_cleanup():
    """
    Test successful SignalCliJSONRPCApi.send_message with filenames and cleanup files.
    """
    filename = _send_message_ok_filenames(cleanup_filenames=True)
    assert not os.path.exists(filename)


def test_send_message_error_filenames():
    """
    Test unsuccessful SignalCliJSONRPCApi.send_message with filenames.
    """
    _send_message_error(filenames=["/foo/bar.gif"], exception="FileNotFoundError")


def test_send_message_ok_attachments_as_bytes():
    """
    Test successful SignalCliJSONRPCApi.send_message with attachments_as_bytes.
    """
    _send_message_ok(attachments_as_bytes=[IMAGE_BYTEARRAY])


def test_send_message_error_attachments_as_bytes():
    """
    Test unsuccessful SignalCliJSONRPCApi.send_message with attachments_as_bytes.
    """
    _send_message_error(attachments_as_bytes=[IMAGE_BYTEARRAY])
