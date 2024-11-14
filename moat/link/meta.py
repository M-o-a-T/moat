"""
Encoding and decoding the metadata for MoaT
"""

from __future__ import annotations

import time

from attrs import define, field
from moat.util import NotGiven
from moat.util.cbor import StdCBOR
from moat.lib.codec.proxy import as_proxy
from base64 import b85decode, b85encode

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Self

_codec = StdCBOR()


def _gen(i):
    ii = i + 1

    def get(self):
        self._len(ii)
        return self[i]

    def set(self, val):
        self._len(ii)
        self[i] = val

    return property(get, set)


def _Meta(a, kw):
    res = MsgMeta(name=NotGiven)
    res.__setstate__(a, kw)
    return res


@as_proxy("_MM", factory=_Meta)
@define(kw_only=True)
class MsgMeta:
    """
    This class encapsulates a message's metadata by encoding them in a
    hopefully-space-saving way.

    XXX: either create a dictionary for origin names, as there aren't many,
    or rely on data compression?

    Currently defined offsets:

    * 0: origin: a string declaring which subsystem created a message.
    * 1: timestamp: the Unix timestamp when the message was originally
         created.

    You can use indexing to address any other array or keyword value.
    Deleting an array member sets it to ``None``.

    """

    a: list[Any] = field(factory=list)
    kw: dict[str, Any] = field(factory=dict)

    origin = _gen(0)
    timestamp = _gen(1)

    def __init__(self, /, name: str | NotGiven | None = None, **kwargs):
        filtered = {
            attribute.name: kwargs[attribute.name]
            for attribute in self.__attrs_attrs__
            if attribute.name in kwargs
        }
        self.__attrs_init__(**kwargs)
        self._clean(name)

    def __getitem__(self, k):
        if isinstance(k, int):
            return self.a[k]
        else:
            return self.kw[k]

    def __getstate__(self):
        return self.a, self.kw

    def __setstate__(self, a, kw):
        self.a = a
        self.kw = kw

    def __setitem__(self, k, v):
        if isinstance(k, slice):
            raise ValueError("Only use positive indices")
        if isinstance(k, int):
            if k < 0:
                raise KeyError(k)  # only positive indices
            elif k == 0 and (not isinstance(v, str) or v == "" or "|" in v or "\\" in v):
                raise ValueError("First item must be a string")
            self._len(k + 1)
            self.a[k] = v
        else:
            self.kw[k] = v

    def __delitem__(self, k):
        if isinstance(k, int):
            self.a[k] = None
        else:
            del self.kw[k]

    def _clean(self, name: str | None):
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

    def _unmap(self, data: list[any]):
        if isinstance(data[-1], dict):
            self.kw = data.pop()
        self.a = data
        dit = iter(data)
        try:
            self.origin = next(dit)
            self.timestamp = next(dit)
        except StopIteration:
            pass

    def encode(self) -> str:
        """
        Encode this object to a string.

        Elements are either UTF-8 strings, introduced by ``|``, or
        some other data, introduced by ``\\``. Strings that include
        either of these characters are treated as "other data".

        Empty strings are encoded as zero-length "other data" elements.
        A value of ``None`` is encoded as an empty string.

        The first item is not marked explicitly.
        It must be a non-empty string.

        Other data are encoded to CBOR, then base85-encoded
        (btoa alphabet).

        The last element may be a dict with free-form content.
        """
        data = self._map()
        res = []
        for d in data:
            if isinstance(d, str) and d != "" and "|" not in d and "\\" not in d:
                if not d and not res:
                    raise ValueError("No empty origins")
                if res:
                    res.append("|")
                if d is not None:
                    res.append(d)
                continue

            if not res:
                raise ValueError("No non-string origins")
            res.append("\\")
            if d != "":
                res.append(b85encode(_codec.encode(d)).decode("utf-8"))
        return "".join(res)

    @classmethod
    def decode(cls, name: str, data) -> Self:
        """
        Decode a string to a `MsgMeta` object.

        Reverses the effect of `encode`.
        """
        res = cls(name)
        ddec = []

        encoded = False
        while data:
            next_enc: bool = None
            cc: int

            c1 = data.find("|")
            c2 = data.find("\\")
            if c1 == -1:
                cc = c2
                next_enc = True
            elif c2 == -1:
                cc = c1
                next_enc = False
            else:
                cc = min(c1, c2)
                next_enc = cc == c2

            if cc == -1:
                d, data = data, None
            else:
                d, data = data[:cc], data[cc + 1 :]
            if encoded:
                if d != "":
                    d = _codec.decode(b85decode(d.encode("utf-8")))
            elif d == "":
                d = None
            ddec.append(d)
            encoded = next_enc

        res._unmap(ddec)
        res._clean(name)
        return res
