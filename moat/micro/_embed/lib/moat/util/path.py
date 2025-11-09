"""
A hacked-up copy of some parts of `moat.util`.
"""

from __future__ import annotations

import re

_PartRE = re.compile("[^:._]+|_|:|\\.")

b64decode = None


class Path(tuple):  # noqa:SLOT001
    """
    somewhat-dummy Path

    half-assed string analysis, somewhat-broken output for non-basics
    """

    def __str__(self):
        def _escol(x):
            x = x.replace(":", "::").replace(".", ":.").replace(" ", ":_")
            return x

        res = []
        if not len(self):
            res.append(":")
        for x in self:
            if isinstance(x, str):
                if x == "":
                    res.append(":e")
                else:
                    if res:
                        res.append(".")
                    res.append(_escol(x))
            elif x is True:
                res.append(":t")
            elif x is False:
                res.append(":f")
            elif x is None:
                res.append(":n")
            elif isinstance(x, (bytes, bytearray, memoryview)):
                if all(32 <= b < 127 for b in x):
                    res.append(":v" + _escol(x.decode("ascii")))  # type:ignore
                    ## The memoryview must be of bytes, thus it supports "decode"
                else:
                    from base64 import b64encode  # noqa: PLC0415

                    res.append(":s" + b64encode(x).decode("ascii"))
                    # no hex
            else:
                res.append(":" + _escol(repr(x)))
        return "".join(res)

    @classmethod
    def build(cls, arr, decoded=False):  # noqa:ARG003
        """
        Constructor to build a Path from an existing list.
        """
        return cls(arr)

    def __repr__(self):
        return f"P({str(self)!r})"

    def __truediv__(self, x):
        return Path(self + (x,))

    def __add__(self, x):
        return Path(tuple(self) + tuple(x))

    def __radd__(self, x):
        return Path(tuple(x) + tuple(self))
