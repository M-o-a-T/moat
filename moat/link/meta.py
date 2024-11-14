"""
Encoding and decoding the metadata for MoaT
"""

from __future__ import annotations

import time

from attrs import define, field
from moat.util import NotGiven
from moat.util.cbor import StdCBOR
from base64 import b85decode,b85encode

_codec = StdCBOR()

def _gen(i):
    ii = i+1

    def get(self):
        self._len(ii)
        return self[i]

    def set(self, val):
        self._len(ii)
        self[i] = val

    return property(get,set)


@define(kw_only=True)
class MsgMeta:
    """
    This class encapsulates a message's metadata, transmitting them
    as an array (possibly followed by a dict), encoding non-strings
    with CBOR and Base85/btoa.

    Currently defined offsets:

    * 0: origin: a string declaring which subsystem created a message.
    * 1: timestamp: the Unix timestamp when the message was originally
         created.
    
    You can use indexing to address any other array or keyword value.
    Deleting an array member sets it to ``None``.

    """
    a:list[Any] = field(factory=list)
    kw:dict[str,Any] = field(factory=dict)

    origin = _gen(0)
    timestamp = _gen(1)

    def __init__(self, /, name:str|NotGiven|None=None, **kwargs):
        filtered = {
            attribute.name: kwargs[attribute.name]
            for attribute in self.__attrs_attrs__
            if attribute.name in kwargs
        }
        self.__attrs_init__(**kwargs)
        self._clean(name)
    
    def __getitem__(self, k):
        if isinstance(k,int):
            return self.a[k]
        else:
            return self.kw[k]

    def __setitem__(self, k, v):
        if isinstance(k,int):
            if isinstance(k, slice) or k < 0:
                raise ValueError("Only use positive indices")
            if isinstance(v,str):
                if ("|" in v or "\\" in v):
                    raise ValueError("Value may not contain '|' or '\\'")
            elif k == 0:
                raise ValueError("First item must be a string")
            self._len(k+1)
            self.a[k] = v
        else:
            self.kw[k] = v

    def __delitem__(self, k):
        if isinstance(k,int):
            self.a[k] = None
        else:
            del self.kw[k]

    def _clean(self, name:str|None):
        if name is NotGiven:
            return
        if name is None:
            if not self.origin:
                raise ValueError("You need to set a name")
        elif not self.origin:
            self.origin = name
        if not self.timestamp:
            self.timestamp = time.time()

    def _len(self, n):
        while len(self.a) < n:
            self.a.append(None)

    def _map(self):
        res = self.a[:]
        while res and res[-1] is None:
            res.pop()
        if self.kw or isinstance(res[-1], dict):
            res.append(self.kw)
        return res

    def _unmap(self, data:list[any]):
        if isinstance(data[-1], dict):
            self.kw = data.pop()
        self.a = data
        dit = iter(data)
        try:
            self.origin = next(dit)
            self.timestamp = next(dit)
        except StopIteration:
            pass

    def encode(self):
        data = self._map()
        res = []
        for d in data:
            if isinstance(d,str):
                if res:
                    res.append("|")
                res.append(d)
            else:
                if not res:
                    raise ValueError("First entry must be a string")
                res.append("\\")
                res.append(b85encode(_codec.encode(d)).decode("utf-8"))
        return "".join(res)

    @classmethod
    def decode(cls, name:str, data):
        res = cls(name)
        ddec = []

        colon = False
        while data:
            ncol:bool = None
            cc:int

            c1 = data.find("|")
            c2 = data.find("\\")
            if c1 == -1:
                cc = c2
                ncol = True
            elif c2 == -1:
                cc = c1
                ncol = False
            else:
                cc = min(c1,c2)
                ncol = cc==c2

            if cc == -1:
                d,data = data,None
            else:
                d,data = data[:cc],data[cc+1:]
            if colon:
                d = _codec.decode(b85decode(d.encode("utf-8")))
            ddec.append(d)
            colon = ncol

        res._unmap(ddec)
        res._clean(name)
        return res
        

        

