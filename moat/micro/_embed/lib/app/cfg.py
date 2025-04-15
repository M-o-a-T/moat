"""
R/W access to configuration data.
"""

from __future__ import annotations

from moat.util import NotGiven
from moat.micro.cmd.base import BaseCmd
from moat.micro.cmd.util.part import enc_part, get_part
from moat.util.compat import log
from moat.util import ExpKeyError


class Cmd(BaseCmd):
    """
    Subsystem to handle config data.

    This app serves the config of the parent subcommand.
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.repeats = {}

    doc_r = dict(_d="read cfg", _0="Path:subpart")

    async def stream_r(self, msg):
        """
        Read (part of) the configuration.

        As configuration data are frequently too large to transmit in one
        go, this code interrogates it step-by-step.

        @p is the path. An empty path is the root.

        If the accessed item is a dict, return data consists of a dict
        (simple keys and their values) and a list (keys for complex
        values).

        Same for a list.
        """
        p = msg[0]
        try:
            res = enc_part(get_part(self._parent.cfg, p))
            if isinstance(res, (list, tuple)):
                await msg.result(*res)
            else:
                await msg.result(res)
        except KeyError as exc:
            raise ExpKeyError(*exc.args)

    doc_w = dict(_d="write cfg", _0="Path:subpart", d="any:Data")

    async def cmd_w(self, p=(), d=NotGiven):
        """
        Online configuration mangling.

        As configuration data are frequently too large to transmit in one
        go, this code interrogates and updates it step-by-step.

        @p is the path. It cannot be empty. Destinations are
        autogenerated. A path element of ``None``, if last,
        appends to a list.

        @d is the data replacing the destination. ``NotGiven`` (or
        omitting the parameter) deletes.

        There is no way to write the current config to the file system.
        You can assemble it on the server and write using app.fs, or you
        can configure a "safe" skeleton setup and update it online after
        booting.
        """
        cur = self._parent.cfg
        if not p:
            raise ValueError("NoPath")
        for pp in p[:-1]:
            try:
                cur = cur[pp]
            except KeyError:
                cur[pp] = {}
                cur = cur[pp]
            except IndexError:
                if len(cur) != pp:
                    raise
                cur.append({})
                cur = cur[pp]
        log("CFG_W %r %r %r", cur, p, d)
        k = p[-1]
        if d is NotGiven:
            del cur[k]
        elif isinstance(cur, list) and k is None:
            cur.append(d)
        else:
            try:
                cur[k] = d
            except IndexError:
                if len(cur) != k:
                    raise
                cur.append(d)

    doc_x = dict(_d="activate new config")

    async def cmd_x(self):
        """
        Activate the new config.
        """
        dest = self._parent
        await dest.reload()
