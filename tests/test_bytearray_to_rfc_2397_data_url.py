# -*- coding: utf-8 -*-
"""
Test for SignalCliJSONRPCApi.bytearray_to_rfc_2397_data_url
"""

from base64 import b64decode

#  pylint: disable=import-error
from pysignalclijsonrpc.api import bytearray_to_rfc_2397_data_url

# pylint: disable=line-too-long
IMAGE = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+P+/HgAFhAJ/wlseKgAAAABJRU5ErkJggg=="
IMAGE_BYTEARRAY = bytearray(b64decode(IMAGE))
RFC_2397_DATA_URL = f"data:image/png;base64,{IMAGE}"


def test_bytearray_to_rfc_2397_data_url_ok():
    """
    Test successful bytearray_to_rfc_2397_data_url.
    """
    assert bytearray_to_rfc_2397_data_url(IMAGE_BYTEARRAY) == RFC_2397_DATA_URL
