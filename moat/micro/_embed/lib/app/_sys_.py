import sys

from moat.util import Proxy, drop_proxy, obj2name

from moat.micro.cmd.base import BaseCmd
from moat.micro.cmd.util import enc_part, get_part, set_part
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

    async def cmd_eval(self, x, p=(), a=None, r=False):
        """
        Evaluation.

        @x can be
        * `None`: an alias for the eval cache
        * a string: evaluated with the eval cache as globals
        * an object (possibly proxied): left as-is

        If @p is a list, @x is replaced by successive attributes or
        indices in @p.

        If @a is set, the result is stored in the eval cache instead of
        being returned.
        Otherwise, if the result is a dict or array, it is returned as a
        two-element list of (dict/list of simple members; list of indices
        of complex members).
        """
        if not self.cache:
            self.cache["self"] = self
            self.cache["root"] = self.root

        if x is None:
            x = self.cache
        elif isinstance(x, str):
            x = eval(x, self.cache)
        x = get_part(x, p)
        if a:
            set_part(self.cache, a, x)
            return None
        else:
            if not isinstance(x, (int, float, list, tuple, dict, Proxy)):
                print("TX=", type(x), file=sys.stderr)
                try:
                    obj2name(x)
                except KeyError:
                    try:
                        obj2name(type(x))
                    except KeyError:
                        x = enc_part(get_part(x.__dict__, p))
            if r:
                return repr(x)
            return x

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
