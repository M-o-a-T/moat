# Copyright (c) 2015 Nicolas JOUANIN  # noqa: D100
#
# See the file license.txt for copying permission.
from __future__ import annotations


class MoatMQTTException(Exception):
    """
    MoatMQTT base exception
    """

    pass


class MQTTException(Exception):
    """
    Base class for all errors refering to MQTT specifications
    """

    pass


class CodecException(Exception):
    """
    Exceptions thrown by packet encode/decode functions
    """

    pass


class NoDataException(Exception):
    """
    Exceptions thrown by packet encode/decode functions
    """

    pass


class InvalidStateError(Exception):
    """
    Exception thrown by Future.
    """

    pass
