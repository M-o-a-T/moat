from __future__ import annotations

import gc
import sys

import machine

from moat.util.compat import log, sleep_ms, ticks_diff, ticks_ms

from ._sys_ import Cmd as _Cmd


class Cmd(_Cmd):
    """
    System stuff that's satellite specific
    """

    doc_state = dict(_d="Root info")

    async def cmd_state(self):
        """
        Return the root info.
        """
        return self.root.i

    doc_rtc = dict(_d="RTC state access", _0="str:Key", fs="bool:filesystem", v="Any:value to set")

    async def cmd_rtc(self, k="state", v=None, fs=None):
        """
        Set/return a MoaT state var.
        """
        from rtc import get_rtc, set_rtc  # noqa: PLC0415

        if v is not None:
            set_rtc(k, v, fs=fs)
        else:
            return get_rtc(k, fs=fs)

    doc_mem = dict(
        _d="memory info",
        _r=dict(
            c="int:bytes freed",
            t="int:gc run(ms)",
            a=["int:alloc now", "int:alloc at boot"],
            f=["int:free now", "int:free at boot"],
        ),
    )

    async def cmd_mem(self):
        """
        Info about memory. Calls `gc.collect`.

        * c: bytes freed by the garbage collector
        * t: time (ms) for the garbage collector to run
        * a: allocation: (now,early)
        * f: free memory: (now,early)
        """
        t1 = ticks_ms()
        f1 = gc.mem_free()
        gc.collect()
        f2 = gc.mem_free()
        a2 = gc.mem_alloc()
        t2 = ticks_ms()
        return dict(
            t=ticks_diff(t2, t1),
            a=(a2, self.root.i.fa),
            f=(f2, self.root.i.fm),
            c=f2 - f1,
        )

    doc_hash = dict(_d="module hash", _0="str:name", l="int:shortened length", _r="str:hash val")

    async def cmd_hash(self, p: str, l: int | None = None):  # noqa:E741
        """
        Get the hash for a built-in module.
        """
        import _hash  # noqa: PLC0415

        res = _hash.hash.get(p, None)
        if l is not None:
            res = res[:l]
        return res

    doc_log = dict(_d="call log", _0="str:text", _99="any:params", _a="any:params")

    async def cmd_log(self, *a, **k):
        """
        Log parameters.
        """
        log(f"Input: {a!r} {k!r}")

    doc_stdout = dict(_d="write stdout", _0="str:text", _99="any:params", _a="any:params")

    async def cmd_stdout(self, *a, **k):
        """
        Print something to stdout.

        WARNING this may disrupt communication if stdout is re-used for the MoaT link.
        """
        print(f"Input: {a!r} {k!r}", file=sys.stderr)

    doc_stderr = dict(_d="write stderr", _0="str:text", _99="any:params", _a="any:params")

    async def cmd_stderr(self, *a, **k):
        """
        Print something to stderr.
        """
        print(f"Input: {a!r} {k!r}", file=sys.stderr)

    doc_boot = dict(
        _d="reboot",
        _0="str:SysBooT",
        _1="int:1=soft,2=hard,3=KbdIntr,4=SysExit",
        _t="int:timeout msec(100)",
    )

    async def cmd_boot(self, code, m, t=100):
        """
        Reboot MoaT.

        @code needs to be "SysBooT".

        @m can be
            1: immediate soft reset
            2: immediate hard reset
            3: return to command line
            4: "clean" soft reset
        """
        if code != "SysBooT":
            raise RuntimeError("wrong")

        async def _boot(t):
            await sleep_ms(t)
            if m == 1:
                machine.soft_reset()
            elif m == 2:
                machine.reset()
            elif m == 3:
                raise KeyboardInterrupt
            elif m == 4:
                raise SystemExit

        self.root.tg.start_soon(_boot, t, _name="_sys.boot1")
        return True

    doc_machid = dict(_d="unique machine id", _r="int")

    async def cmd_machid(self):
        """
        Return the machine's unique ID. This is the bytearray returned by
        `micropython.unique_id`.
        """
        return machine.unique_id()

    doc_pin = dict(
        _d="direct digital pin", _0="int:pin#", v="bool:value to set", _r="bool:hw state"
    )

    async def cmd_pin(self, n, v=None, **kw):
        """
        Set or read a digital pin.
        """
        p = machine.Pin(n, **kw)
        if v is not None:
            p.value(v)
        return p.value()

    doc_adc = dict(_d="direct analog pin", _0="int:pin#", _r="int:16-bit value")

    async def cmd_adc(self, n):
        """
        Read an analog pin.
        """
        p = machine.ADC(n)
        return p.read_u16()  # XXX this is probably doing a sync wait
