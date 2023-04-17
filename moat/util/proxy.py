"""
This module contains proxy helpers.
"""

from .impl import NotGiven

__all__ = ["Proxy", "NoProxyError", "as_proxy", "name2obj", "obj2name"]


class NoProxyError(ValueError):
    "Error for nonexistent proxy values"
    pass  # pylint:disable=unnecessary-pass


class Proxy:
    """
    A proxy object, i.e. a placeholder for things that cannot pass through MsgPack.
    """

    def __init__(self, name, *data):
        self.name = name
        self.data = data

    def __repr__(self):
        return (
            f"{self.__class__.__name__}({repr(self.name)},"
            + ",".join(repr(x) for x in self.data)
            + ")"
        )

    def ref(self):
        """Dereferences the proxy"""
        return name2obj(self.name)


# _pkey = 1
_CProxy: dict[str, object] = {}
_RProxy: dict[int, str] = {}


def name2obj(name, obj=NotGiven):
    """
    Translates Proxy name to referred object

    Raises `KeyError` if not found.
    """
    if obj is NotGiven and _CProxy:
        return _CProxy[name]
    if _CProxy.get(name, None) is not obj:
        raise KeyError(name)  # exists
    _CProxy[name] = obj
    return None


def obj2name(obj, name=NotGiven):
    """
    Translates Proxy object to proxied name

    If a name is given, set it.

    Raises `KeyError` if not found and no name given, or if the oid
    already has a different name.
    """
    if name is NotGiven:
        return _RProxy[id(obj)]
    oid = id(obj)
    if _RProxy.get(oid, None) != name:
        raise KeyError(name)  # exists
    _RProxy[oid] = name
    return None


def as_proxy(name, obj=NotGiven):
    """
    Export an object or class as a named proxy.
    """

    def _proxy(obj):
        name2obj(name, obj)
        obj2name(obj, name)
        return obj

    if obj is NotGiven:
        return _proxy
    else:
        _proxy(obj)
        return obj


as_proxy("-", NotGiven)
