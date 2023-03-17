from ._cmd import *
from ._cmd import BaseCmd as _BaseCmd

class BaseCmd(_BaseCmd):
    def cmd__dir(self):
        """
        Rudimentary introspection. Returns a list of available commands @c,
        submodules @d, and local commands @e.

        @j is True if there's a generic command handler.
        """
        e = []
        res = super().cmd__dir()
        for k in dir(self):
            if k.startswith("loc_") and k[4] != '_':
               e.append(k[4:])
        if e:
            res["e"]= e
        return res

