"""
RTC access
"""

from __future__ import annotations

from moat.util import NotGiven, enc_part, get_part, merge, set_part
from moat.lib.rpc import BaseCmd
from moat.micro.rtc import RTC
from moat.util.exc import ExpKeyError

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.path import PathElem
    from moat.lib.rpc import Msg


class _NotGiven:
    pass


class Cmd(BaseCmd):
    """
    Subsystem to handle RTC data.

    This app serves access to the config snippet(s) stored in the system's
    RTC chip.
    """

    doc = dict(_c=dict(_d="RTC access"))

    async def cmd(self, k=_NotGiven, v=_NotGiven):
        """
        Direct R/W access to RTC.

        Args:
            k: Key to access.
            v: Value to set. If not given, returns current value.

        This function does not list keys. Use :meth:`stream` for that.

        The name can also be passed as next-to-last path element.
        (The last is `w`.)
        """
        if k is _NotGiven:
            return await RTC.keys()
        if v is _NotGiven:
            return await RTC.get(k)
        else:
            await RTC.set(k, v)

    doc_r = dict(_d="read data", p="path", _r="parts")

    def __init__(self, cfg: dict):
        super().__init__(cfg)
        self._data = {}

    async def stream_r(self, msg: Msg):
        """
        Read (part of) the RTC data area.

        As data are frequently too clunky to transmit in one go, this code
        interrogates the state step-by-step.

        Args:
            0(str): the config entry.
            1(Path): the path to access within the entry.

        If the accessed item is a dict, return data consists of a dict
        (simple keys and their values) and a list (keys for complex
        values).

        Same for a list.

        RTC.get() is called when the path is empty, otherwise the cached
        value is used.  Keyword args are passed to it.
        """
        # This is a stream command because it returns the enc_part output
        # as multi-element return values.
        try:
            n = msg.kw.pop("n")
        except KeyError:
            n = msg[0]
        p = msg.kw.pop("p", ())

        try:
            if not p:
                self._data[n] = res = await RTC.get(n, **msg.kw)
            else:
                res = get_part(self._data[n], p)
            res = enc_part(res)
            if isinstance(res, (list, tuple)):
                await msg.result(*res)
            else:
                await msg.result(res)
        except KeyError as exc:
            raise ExpKeyError(*exc.args) from None

    doc_w = dict(_d="write data", _0="str:name", _1="any:data")

    async def stream_w(self, msg: Msg):
        """
        Write to RTC.

        Args:
            name(str): Name of the entry.
            data(Any): Data to store. `NotGiven` deletes.

        The name can also be passed as next-to-last path element.
        (The last is `w`.)
        """
        try:
            n = msg.kw.pop("n")
        except KeyError:
            n = msg[0]
            off = 1
        else:
            off = 0
        try:
            d = msg.kw.pop("d")
        except KeyError:
            d = msg[off]

        return await RTC.set(n, d, **msg.kw)

    doc_c = dict(_d="write cached data", _0="str:name", _1="path:pos", d="any:deletes if missing")

    async def stream_c(self, msg: Msg):
        """
        Write to the cached data.

        As data are sometimes too large to transmit in one go, this code
        updates the state step-by-step.

        Args:
            0(str): the config entry.
            1(Path): the path to access within the entry.
            d(Any): data.

        If the path is empty, the cached data is replaced/dropped depending
        on whether *d* is `NotGiven`.

        This method does not write to RTC. Use :meth:`cmd_x` for that.
        """
        n = msg.kw.pop("n")
        p = msg.kw.pop("p", ())
        d = msg.kw.pop("d", NotGiven)
        keep = msg.kw.pop("keep", False)
        if not p:
            if d is NotGiven:
                self._data.pop(n, None)
            else:
                self._data[n] = d
        else:
            set_part(self._data.setdefault(n, {}), p, d, keep=keep)

    doc_x = dict(_d="activate data")

    async def cmd_x(self, n: str, **kw):
        """
        Write the current cache entry with this name to RTC.

        If no such entry exists, the datum is deleted from RTC.

        This command replaces the RTC config if the name "rtc" is written.
        It updates (not replaces) the global config if "cfg" is written.

        """
        d = self._data.pop(n, NotGiven)
        res = await RTC.set(n, d, **kw)
        if d is not NotGiven:
            if n == "rtc":
                RTC.init(d)
            elif n == "cfg":
                merge(self.root.cfg, d, replace=True)
                await self.root.reload()
        return res

    async def stream(self, msg: Msg):
        """
        Get all data.

        Arguments:
            keys: flag whether to get only keys. If `False`, return
                  ``(key,value)`` pairs. The default is `True`.
        """
        keys = msg.kw.get("keys", True)
        fs = msg.kw.get("fs", None)
        async with msg.stream() as ms:
            for k in await RTC.keys(fs=fs):
                if not keys:
                    k = (k, await RTC.get(k, fs=fs))  # noqa:PLW2901
                await ms.send(k)

    async def handle(self, msg: Msg, rcmd: list[PathElem]):
        """
        Handler override for adding the name to the path.

        rcmd is reversed, so rtc.cfg.w arrives as ["w", "cfg"]
        """
        if len(rcmd) == 2 and rcmd[1][-1] != "_" and rcmd[0] in "rwcx" and "n" not in msg:
            msg.kw["n"] = rcmd.pop()
        await super().handle(msg, rcmd)
