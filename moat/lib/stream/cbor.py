"""
CBOR message handling for streams (CPython-specific).
"""

from __future__ import annotations

from moat.lib.codec import get_codec

from ._cbor import _CBORMsgBlk, _CBORMsgBuf


class CBORMsgBuf(_CBORMsgBuf):
    """
    structured messages > bytestream

    Use this if your stream is reliable (TCP, USB, …) but doesn't support
    message boundaries.
    """

    async def setup(self):  # noqa:D102
        await super().setup()
        self.codec = get_codec(self.cfg.get("codec", "std-cbor"))


class CBORMsgBlk(_CBORMsgBlk):
    """
    structured messages > chunked bytestrings

    Use this if the layer below supports byte boundaries
    (one bytestring-ized message per call).
    """

    async def setup(self):  # noqa:D102
        await super().setup()
        self.codec = get_codec(self.cfg.get("codec", "std-cbor"))
