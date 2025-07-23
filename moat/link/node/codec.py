"""
This module contains the MoaT-Link nodes used as codecs.
"""

from __future__ import annotations

from logging import getLogger

from attrs import define, field

from moat.util import Path, make_proc

from . import Node

logger = getLogger(__name__)

@define
class CodecNode(Node):
    """
    This node type is used as a codec.
    """
    _enc = field(init=False,default=None)
    _dec = field(init=False,default=None)

    def enc_value(self, value, entry=None, **kv):
        if self._enc is not None:
            value = self._enc(value=value, entry=entry, data=self._data, **kv)
        return value

    def dec_value(self, value, entry=None, **kv):
        if self._dec is not None:
            value = self._dec(value=value, entry=entry, data=self._data, **kv)
        return value

    def set_(self, path:Path, data:Any, meta:MsgMeta):
        super().set_(path,data,meta)

        enc = None
        dec = None
        if data is not None and data.get("decode",None) is not None:
            dec = make_proc(data["decode"], ("value",), path)

        if data is not None and data.get("encode",None) is not None:
            enc = make_proc(data["encode"], ("value",), path)

        self._enc = enc
        self._dec = dec
