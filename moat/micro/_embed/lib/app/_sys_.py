"""
System access app
"""

from __future__ import annotations

from moat.util import Path
from moat.lib.codec.proxy import Proxy, drop_proxy
from moat.micro.cmd.base import BaseCmd
from moat.micro.cmd.util.part import enc_part, get_part, set_part
from moat.micro.stacks.util import TEST_MAGIC


class Cmd(BaseCmd):
    """
    Generic system specific commands
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.cache = {}

    doc_test = dict(_d="enc test str", _r="str:fancy string")

    async def cmd_test(self):
        """
        Returns a test string: r CR n LF - NUL c ^C e ESC !

        Use this to verify that nothing mangles anything.
        """
        return TEST_MAGIC

    doc_unproxy = dict(_d="drop proxy", _0="Proxy")

    async def cmd_unproxy(self, p):
        """
        Tell the client to forget about a proxy.

        @p accepts either the proxy's name, or the proxied object.
        """
        if p == "" or p == "-" or p[0] == "_":
            raise RuntimeError("cannot be deleted")
        drop_proxy(p)

    doc_eval = dict(
        _d="eval",
        _0="Proxy|str|list",
        r="str|bool:cache result",
        a="list:fn args",
        k="dict:fn kwargs",
    )

    async def cmd_eval(self, x, r: str | bool = False, a=None, k=None):
        """
        Debugging/Introspection/Evaluation.

        @x can be
        * a string: evaluated, context is the eval cahce
        * a list: descend into an object.
          the first item must be a proxy (object reference)
          or a string (eval cache lookup)
        * an object (possibly proxied): left as-is

        Then if a or k is not None, assume that the result is a function
        and call it.

        If @r is  a string, the result is stored in the eval cache
        under that name. A list is interpreted as an accessor:
        ``x=42, r=('a','b','c')`` assigns ``cache['a'].b.c=42``.
        Nothing is returned in these cases.

        If @r is False *or* if the result is a dict or array, it is
        returned as a two-element list of (dict/list of simple members;
        list of indices of complex members). For objects, a third element
        contains the object type's name.
        If @r is True, the result's ``repr`` is returned.
        Otherwise (@r is ``None``), a proxy is returned.
        """
        if not self.cache:
            self.cache["self"] = self
            self.cache["root"] = self.root

        if isinstance(x, str):
            try:
                res = eval(x, self.cache)
            except SyntaxError:
                exec(x, self.cache)  # noqa:S102
                res = None
        elif isinstance(x, (tuple, list, Path)):
            res = x[0]
            if isinstance(res, str):
                res = self.cache[res]
            res = get_part(res, x[1:])
        else:
            res = x

        # call it?
        if a is not None or k is not None:
            res = res(*(a or ()), **(k or {}))
            if hasattr(res, "throw"):
                res = await res

        # store it?
        if isinstance(r, str):
            # None: drop from the cache
            if res is None:
                del self.cache[r]
            else:
                self.cache[r] = res
            return res is not None

        if isinstance(r, (list, tuple)):
            set_part(self.cache, r, res)
            return None

        if isinstance(res, (dict, list, tuple)):
            # dicts+lists always get encoded
            res = enc_part(res)
        elif not isinstance(res, (int, float, Proxy)):
            if r is True:
                return repr(res)
            if r is False:
                try:
                    rd = res.__dict__
                except AttributeError:
                    pass
                else:
                    res = enc_part(rd, res.__class__.__name__)
        return res

    doc_ping = dict(_d="Reply test", m="any:Return data", _r=dict(m="any:Return data"))

    async def cmd_ping(self, m=None):
        """
        Echo @m.

        This is for humans and testing. Don't use it for automated keepalive.
        """
        return {"m": m}
