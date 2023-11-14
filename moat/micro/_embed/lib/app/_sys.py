from __future__ import annotations

import gc

import machine

from moat.micro.compat import sleep_ms, ticks_diff, ticks_ms

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
        from moat.rtc import get_rtc,set_rtc

        if state is not None:
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
        return dict(t=ticks_diff(t2, t1), a=(a2,self.root.i.fa), f=(f2,self.root.i.fm), c=f2 - f1)

    async def cmd_boot(self, code):
        """
        Reboot the system (soft reset).

        @code needs to be "SysBooT".
        """
        if code != "SysBooT":
            raise RuntimeError("wrong")

        async def _boot():
            await sleep_ms(100)
            machine.soft_reset()

        await self.root.tg.spawn(_boot, _name="_sys.boot1")
        return True

    async def cmd_reset(self, code):
        """
        Reboot the system (hard reset).

        @code needs to be "SysRsT".
        """
        if code != "SysRsT":
            raise RuntimeError("wrong")

        async def _boot():
            await sleep_ms(100)
            machine.reset()

        await self.root.tg.spawn(_boot, _name="_sys.boot2")
        return True

    async def cmd_stop(self, code):
        """
        Terminate MoaT and go back to MicroPython.

        @code needs to be "SysStoP".
        """
        # terminate the MoaT stack w/o rebooting
        if code != "SysStoP":
            raise RuntimeError("wrong")

        async def _boot():
            await sleep_ms(100)
            await self.request.send_nr("link", False)
            await sleep_ms(100)
            raise SystemExit

        await self.request._tg.spawn(_boot, _name="_sys.boot3")  # noqa:SLF001
        return True

    async def cmd_machid(self):
        """
        Return the machine's unique ID. This is the bytearray returned by
        `micropython.unique_id`.
        """
        return machine.unique_id()

    async def cmd_rtc(self, d=None):
        """
        Set, or query, the current time.
        """
        if d is None:
            return machine.RTC.now()
        else:
            machine.RTC((d[0], d[1], d[2], 0, d[3], d[4], d[5], 0))

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
