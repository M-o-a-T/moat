"""
Import legacy stream classes from their new locations.

This module provides backward compatibility by re-exporting classes
that have been moved to moat.lib.stream.
"""

from __future__ import annotations

from moat.lib.stream._cbor import _CBORMsgBlk as _CBORMsgBlk
from moat.lib.stream._cbor import _CBORMsgBuf as _CBORMsgBuf
from moat.lib.stream._console import _CReader as _CReader
from moat.lib.stream._serial import SerialPackerBlkBuf as SerialPackerBlkBuf

__all__ = [
    "SerialPackerBlkBuf",
    "_CBORMsgBlk",
    "_CBORMsgBuf",
    "_CReader",
]
