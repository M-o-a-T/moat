from __future__ import annotations

import gc
import sys

import machine

from moat.micro.compat import sleep_ms, ticks_diff, ticks_ms, log

from ._sys_ import Cmd as _Cmd

class Cmd(_Cmd):
    """
    System stuff that's satellite specific
    """

    async def cmd_state(self):
        """
        Return the root info.
        """
        return self.root.i

    async def cmd_rtc(self, k="state", v=None, fs=None):
        """
        Set/return a MoaT state.
        """
        from moat.rtc import get_rtc, set_rtc

        if v is not None:
            set_rtc(k, v, fs=fs)
        else:
            return get_rtc(k, fs=fs)

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

    async def cmd_hash(self, p: str, l: int | None = None):
        """
        Get the hash for a built-in module.
        """
        import _hash

        res = _hash.hash.get(p, None)
        if l is not None:
            res = res[:l]
        return res

    async def cmd_log(self, *a, **k):
        """
        Log parameters.
        """
        log("Input: %r %r" % (a,k))

    async def cmd_stdout(self, *a, **k):
        """
        Print something.
        """
        print("Input: %r %r" % (a,k))

    async def cmd_stderr(self, *a, **k):
        """
        Print something.
        """
        print("Input: %r %r" % (a,k), file=sys.stderr)

    async def cmd_boot(self, code, m):
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

        async def _boot():
            await sleep_ms(100)
            if m == 1:
                machine.soft_reset()
            elif m == 2:
                machine.reset()
            elif m == 3:
                raise KeyboardInterrupt
            elif m == 4:
                raise SystemExit

        await self.root.tg.spawn(_boot, _name="_sys.boot1")
        return True

    async def cmd_machid(self):
        """
        Return the machine's unique ID. This is the bytearray returned by
        `micropython.unique_id`.
        """
        return machine.unique_id()

    async def cmd_pin(self, n, v=None, **kw):
        """
        Set or read a digital pin.
        """
        p = machine.Pin(n, **kw)
        if v is not None:
            p.value(v)
        return p.value()

    async def cmd_adc(self, n):
        """
        Read an analog pin.
        """
        p = machine.ADC(n)
        return p.read_u16()  # XXX this is probably doing a sync wait
