"""
Encoding and decoding the metadata for MoaT
"""

from __future__ import annotations

import time
from base64 import b85decode, b85encode

from attrs import define, field
import ruyaml as yaml

from moat.lib.codec.proxy import as_proxy
from moat.util import NotGiven
from moat.util.cbor import StdCBOR
from moat.util.times import ts2iso

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any, Self, Literal
    from types import EllipsisType

_codec = StdCBOR()

SafeRepresenter = yaml.representer.SafeRepresenter  # pyright:ignore


def _gen(i):
    ii = i + 1

    def get_(self):
        self._len(ii)
        return self[i]

    def set_(self, val):
        self._len(ii)
        self[i] = val

    return property(get_, set_)


@as_proxy("_MM")
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

    The "source" attribute is used for preventing loops within a program.
    It is not saved.
    """

    a: list[Any] = field(factory=list)
    kw: dict[str, Any] = field(factory=dict)

    origin = _gen(0)
    timestamp = _gen(1)

    source: Any = None

    def __init__(self, /, name: str | EllipsisType | None = None, **kwargs):  # pyright: ignore
        vals = {}
        for k in dir(self):
            v = getattr(type(self), k, None)
            if isinstance(v, property) and (val := kwargs.pop(k, NotGiven)) is not NotGiven:
                vals[k] = val
        self.__attrs_init__()  # pyright:ignore
        self.kw = kwargs
        for k, v in vals.items():
            setattr(self, k, v)
        self._clean(name)

    def __repr__(self):
        res = f"‹{self.__class__.__name__} {self.a!r}"
        if self.kw:
            res += ","+repr(self.kw)
        if self.source is not None:
            res += " src="+self.source
        res += "›"
        return res

    def dump(self):
        """
        Emit this as an array, ready for sending.
        """
        if self.kw or self.a and isinstance(self.a[-1], dict):
            return self.a + [self.kw]
        return self.a

    def repr(self):
        """
        Emit this as a dict, ready for debugging.
        """
        kw = dict(self.kw)
        kw["origin"] = self.origin
        kw["timestamp"] = self.timestamp
        kw["_timestamp"] = ts2iso(self.timestamp, delta=True, msec=3)
        return kw

    @classmethod
    def restore(cls, a, kw=NotGiven):
        m = object.__new__(cls)
        if kw is NotGiven:
            if a and isinstance(a[-1], dict):
                kw = a.pop()
            else:
                kw = {}
        source = kw.pop("source", None)
        if isinstance(a, tuple):
            raise TypeError("why a tuple?")  # XXX
            a = list(a)
        m.a = a
        m.kw = kw
        m.source = source
        return m
    _moat__restore = restore

    def __getitem__(self, k):
        if isinstance(k, int):
            return self.a[k]
        else:
            return self.kw[k]

    def __getstate__(self):
        return self.a, self.kw

    def __setstate__(self, akw):
        self.a, self.kw, *_ = akw

    def __setitem__(self, k, v):
        if isinstance(k, slice):
            raise ValueError("Only use positive indices")  # noqa:TRY004
        if isinstance(k, int):
            if k < 0:
                raise KeyError(k)  # only positive indices
            elif k == 0 and (not isinstance(v, str) or v == "" or "/" in v or "\\" in v):
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

    def _clean(self, name: str | EllipsisType | None):
        if name is NotGiven:
            return
        if name is None:
            if not self.origin:
                raise ValueError("You need to set a name")
        elif not self.origin:
            assert isinstance(name,str)
            if not name.startswith("via:"):
                name = f"via:{name}"
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

    def _unmap(self, data: list[Any]):
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

        Elements are either UTF-8 strings, introduced by ``/``, or
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
            if isinstance(d, str) and d != "" and "/" not in d and "\\" not in d:
                if not d and not res:
                    raise ValueError("No empty origins")
                if res:
                    res.append("/")
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
    def decode(cls, name: str, data: str) -> Self:
        """
        Decode a string to a `MsgMeta` object.

        Reverses the effect of `encode`.
        """
        res = cls(NotGiven)
        ddec = []

        encoded = False
        while data:
            next_enc: bool
            cc: int

            c1 = data.find("/")
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
                d, data = data, ""
            else:
                d, data = data[:cc], data[cc + 1 :]
            if encoded:
                if d != "":
                    d = _codec.decode(b85decode(d.encode("utf-8")))
            elif d == "":
                d = None
            ddec.append(d)
            encoded = next_enc

        res._unmap(ddec)  # noqa:SLF001
        res._clean(name)  # noqa:SLF001
        return res

def _meta_repr(dumper, data):
    return dumper.represent_scalar("!Meta", repr(data))

SafeRepresenter.add_representer(MsgMeta, _meta_repr)

