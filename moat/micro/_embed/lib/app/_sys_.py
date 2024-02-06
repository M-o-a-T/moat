"""
System access app
"""
from __future__ import annotations

import sys

from moat.util import Proxy, drop_proxy, obj2name
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

    async def cmd_test(self):
        """
        Returns a test string: r CR n LF - NUL c ^C e ESC !

        Use this to verify that nothing mangles anything.
        """
        return TEST_MAGIC

    async def cmd_unproxy(self, p):
        """
        Tell the client to forget about a proxy.

        @p accepts either the proxy's name, or the proxied object.
        """
        if p == "" or p == "-" or p[0] == "_":
            raise RuntimeError("cannot be deleted")
        drop_proxy(p)

    async def cmd_eval(self, x, r:str|bool = False, a=None, k=None):
        """
        Debugging/Introspection/Evaluation.

        @x can be
        * a string: member of the eval cache
        * a list: descend into an object on the eval cache
        * an object (possibly proxied): left as-is

        If @p is a list, @x is replaced by successive attributes or
        indices in @p.

        Then if a or k is not None, the given function is called.

        If @r is  a string, the result is stored in the eval cache
        under that name instead of being returned. If it's a list,
        it's interpreted as a 
        If True, its ``repr`` is returned.
        Otherwise, if the result is a dict or array, it is returned as a
        two-element list of (dict/list of simple members; list of indices
        of complex members).
        The same thing happens if @r is False.
        Otherwise a proxy is returned.

        """
        if not self.cache:
            self.cache["self"] = self
            self.cache["root"] = self.root

        if isinstance(x, str):
            res = self.cache[x]
            print("RL=", type(res), repr(res), file=sys.stderr)
        elif isinstance(x, (tuple,list)):
            res = get_part(self.cache, x)
            print("RP=", type(res), repr(res), file=sys.stderr)
        else:
            res = x
            print("RX=", type(res), repr(res), file=sys.stderr)

        # call it?
        if a is not None or k is not None:
            res = res(*(a or ()), **(k or {}))
            if hasattr(res, "throw"):
                res = await res

        # store it?
        if isinstance(r,str):
            # None: drop from the cache
            if res is None:
                del self.cache[r]
            else:
                self.cache[r] = res
            return res is not None

        if isinstance(r,(list,tuple)):
            set_part(self.cache, r, res)
            return None

        if isinstance(res,(dict,list,tuple)):
            # dicts+lists always get encoded
            res = enc_part(res)
        elif not isinstance(res, (int, float, Proxy)):
            print("TX=", type(res), r, file=sys.stderr)
            if r is True:
                return repr(res)
            if r is False:
                try:
                    rd = res.__dict__
                except AttributeError:
                    pass
                else:
                    res = enc_part(res.__dict__, res.__class__.__name__)
        return res

    async def cmd_info(self):
        """
        Returns some basic system info.
        """
        d = {}
        fb = self.root.is_fallback
        if fb is not None:
            d["fallback"] = fb
        d["path"] = sys.path
        return d

    async def cmd_ping(self, m=None):
        """
        Echo @m.

        This is for humans. Don't use it for automated keepalive.
        """
        return {"m": m, "rep": repr(m)}
