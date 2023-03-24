"""
This module contains proxy helpers.
"""

from functools import partial

import msgpack

from .dict import attrdict
from .path import Path
from .impl import NotGiven

__all__ = ["Proxy", "NoProxyError", "as_proxy", "_CProxy", "_RProxy"]


class Proxy:
    """
    A proxy object, i.e. a placeholder for things that cannot pass through MsgPack.
    """

    def __init__(self, name):
        self.name = name

    def __repr__(self):
        return f"{self.__class__.__name__}({self.name !r})"


class NoProxyError(ValueError):
    "Error for nonexistent proxy values"
    pass  # pylint:disable=unnecessary-pass

class ProxyObj:
    def __init__(self, name, *data):
        self.name = name
        self.data = data

    def __repr__(self):
        return f"RemoteObj({repr(self.name)},"+",".join(repr(x) for x in data)+")"

# _pkey = 1
_CProxy:dict[str,object] = {}
_RProxy:dict[int,str] = {}

def as_proxy(name, obj=NotGiven):
    """
    Export an object or class as a named proxy.
    """
    def _proxy(obj):
        _CProxy[name] = obj
        _RProxy[id(obj)] = name
        return obj
    if obj is NotGiven:
        return _proxy
    else:
        _proxy(obj)
        return obj

as_proxy("-")(NotGiven)

