"""
Adaptor for MicroPython streams.
"""

from __future__ import annotations

from moat.util import DProxy, NoProxyError, Proxy, get_proxy, name2obj, obj2name

from msgpack import ExtType, Unpacker, packb

# msgpack encode/decode


def _decode(code, data):
    # decode an object, possibly by building a proxy.

    if code == 4:
        n = str(data, "utf-8")
        try:
            return name2obj(n)
        except KeyError:
            if Proxy is None:
                raise NoProxyError(n) from None
            return Proxy(n)
    elif code == 5:
        s = Unpacker(None)
        s.feed(data)

        s, *d = list(s)
        st = d[1] if len(d) > 1 else {}
        d = d[0]
        try:
            p = name2obj(s)
            if hasattr(p, "__setstate__"):
                o = p(*d)
                p.__setstate__(st)
            else:
                o = p(*d, **st)
        except KeyError:
            o = DProxy(s, *d, **st)
        except TypeError:
            o = p(*d)
            try:
                o.__dict__.update(st)
            except AttributeError:
                for k, v in st.items():
                    setattr(o, k, v)
        return o
    return ExtType(code, data)


def _encode(obj):
    # encode an object by building a proxy.

    if type(obj) is Proxy:
        return ExtType(4, obj.name.encode("utf-8"))
    if type(obj) is DProxy:
        return ExtType(
            5,
            packb(obj.name) + packb(obj.a, default=_encode) + packb(obj.k, default=_encode),
        )

    try:
        k = obj2name(obj)
        return ExtType(4, k.encode("utf-8"))
    except KeyError:
        pass
    try:
        k = obj2name(type(obj))
    except KeyError:
        k = get_proxy(obj)
        return ExtType(4, k.encode("utf-8"))
    else:
        try:
            p = obj.__reduce__
        except AttributeError:
            try:
                p = obj.__dict__
            except AttributeError:
                p = {}
                for n in dir(obj):
                    if n.startswith("_"):
                        continue
                    p[n] = getattr(obj, n)
            p = ((), p)
        else:
            p = p()
            if hasattr(p[0], "__name__"):  # grah
                if p[0].__name__ == "_reconstructor":
                    p = (p[1][0], ()) + tuple(p[2:])
                elif p[0].__name__ == "__newobj__":
                    p = (p[1][0], p[1][1:]) + tuple(p[2:])

            assert p[0] is type(obj), (obj, p)
            p = p[1:]
        return ExtType(5, packb(k) + b"".join(packb(x, default=_encode) for x in p))
