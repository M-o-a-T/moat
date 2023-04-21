"""
Server side of BaseCmd

extends BaseCmd to also return loc_* functions
"""

from ._cmd import BaseCmd as _BaseCmd
from ._cmd import Request  # pylint:disable=unused-import


class BaseCmd(_BaseCmd):
    """
    The server-side BaseCmd class also returns a list of local commands in
    `_dir`.
    """
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
            res["e"] = e
        return res

    loc__dir = cmd__dir
