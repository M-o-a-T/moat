"""
Types that describe a modbus device, as read from file
"""

import time
from collections.abc import Mapping
from pathlib import Path as FSPath

import anyio

from moat.util import attrdict, yload, Path, combine_dict, merge
from ..client import Unit, Host, Slot, ModbusError
from ..typemap import get_type2, get_kind
from ..types import InputRegisters

import logging
logger = logging.getLogger(__name__)

class BadRegisterError(ValueError):
    pass

class NotARegisterError(ValueError):
    pass


def fixup(d,root=None,path=Path(), post=None):
    if root is None:
        root = d
    try:
        inc = d.pop("include")
    except KeyError:
        pass
    else:
        if isinstance(inc, tuple):
            inc = list(inc)
        elif not isinstance(inc,list):
            inc = [inc]
        for i,dd in enumerate(inc):
            with (data/dd).open("r") as df:
                dd = yload(df, attr=True)
            inc[i] = fixup(dd,dd,Path())
        inc.reverse()
        d = combine_dict(d, *inc, cls=attrdict)

    try:
        refs = d.pop("ref")
    except KeyError:
        pass
    else:
        for i,p in enumerate(refs):
            refs[i] = root._get(p)

        refs.reverse()
        d = combine_dict(d, *refs, cls=attrdict)
    
    for k,v in d.items():
        if isinstance(v,Mapping):
            d[k] = fixup(v,root,path/k)

    if post is not None:
        d = post(d,path)

    return d


class Register:
    """A single modbus device's register.

    This class duck-types as a moat.modbus.types.BaseValue."""

    last_gen = -1

    def __init__(self, d, path, unit):
        try:
            s = d.type
        except AttributeError:
            raise AttributeError(f"No type in {path}") from None
        try:
            l = d.len
        except AttributeError:
            if s in {"int","uint"}:
                l = 1
            elif s == "float":
                l = 2
            else:
                raise BadRegisterError("no length")

        self.reg = get_type2(s, l)()

        self.register = d.register
        try:
            self.reg_type = get_kind(d.reg_type)
        except AttributeError:
            self.reg_type = InputRegisters

        if "slot" in d:
            slot = unit.slot(d.slot)
            slot.add(self.reg_type, offset=self.register, cls=self.reg)
        self.data = d
        self.factor = 10 ** self.data.get("scale",0) * self.data.get("factor",1)
        self.offset = self.data.get("offset", 0)
        self.path = path

    def __aiter__(self):
        return self.reg.__aiter__()

    @property
    def value(self):
        if self.reg.value is None:
            return None
        return self.reg.value * self.factor + self.offset

    @value.setter
    def value(self, val):
        self.reg.value = (val-offset)/self.factor

    @property
    def len(self):
        return self.reg.len

    def encode(self):
        return self.reg.encode()

    def decode(self, regs):
        self.reg.decode(regs)

    @property
    def changed(self):
        return self.reg.changed

    @property
    def gen(self):
        return self.reg.gen

    def __repr__(self):
        return f"‹{str(self.reg_type)[0].lower()}{self.register} @{self.path}:{self.value}›"

    __str__ = __repr__


data = FSPath(__file__).parent / "_data"

class Device:
    """A modbus device.

    The idea is to use the device description file as a template.

    You augment that file with "slot" data, i.e. named intervals,
    plus processing instructions. The instructions may contain slot names.

    For each slot, you periodically call `await dev.update(slotname,
    processor)`. The system will fetch the data, call a given postprocessor
    for each item (which might forward the value to MQTT), and return
    the list of registers.
    """

    def __init__(self, client, factory=Register):
        self.client = client
        self.factory = factory

    def load(self, path:str=None, data:dict=None):
        """Load a device description from @path, augmented by @data"""
        if path is None:
            d = attrdict()
        else:
            path = data / path
            d = yload(path, attr=True)
        if data is not None:
            d = merge(d,data)
        self.data = fixup(d,d,Path())

        self.host = self.client.host(self.data.src.host, self.data.src.get('port'))
        self.unit = self.host.unit(self.data.src.unit)
        self.add_registers()

    def add_registers(self):
        def a_r(d,path=Path()):
            seen = False
            for k,v in d.items():
                if not isinstance(v,dict):
                    continue
                if a_r(v, path/k):
                    seen = True
                    if "register" in v:
                        logger.warning(f"{path/k} has a sub-register: ignored")
                        continue
                    continue

                if "register" in v:
                    d[k] = self.factory(v, path/k, self.unit)
                    seen = True
                elif "slot" in v:
                    logger.warning(f"{path/k} is not a register")
            return seen
        a_r(self.data)

    def get(self, path:Path):
        dev = self.data._get(path)
        if not isinstance(dev, Register):
            raise NotARegisterError(path)
        return dev

    @property
    def slots(self):
        """The slots of this unit"""
        return self.unit.slots

    async def update(self, slot:Slot, proc=None):
        """Update a slot. Calls @proc with each register (in parallel)."""
        vals = await slot.getValues()
        if proc is not None:
            async with anyio.create_task_group() as tg:
                for d in vals.values():
                    for v in d.values():
                        tg.start_soon(proc, v)
        return vals

    async def poll_slot(self, slot: str):
        """Periodically poll this slot"""
#slots:
#  1sec:
#    time: 1
#    align: false
## align=True: wait for the next multiple
## align=False: fetch now, *then* wait for the next multiple
## align=None: fetch now, wait for the timespan
        s = self.data.slots[slot]
        sl = self.unit.slot(slot)
        al = s.get("align", None)
        if al is not None:
            t = time.time()
            r = (-t)%s.time
            if al:
                await anyio.sleep(r)
        nt = time.monotonic()

        while True:
            logger.debug(f"{self.host} {slot}: updating {sl}")
            try:
                await self.update(sl)
            except ModbusError as err:
                logger.error(f"{self.host} {slot}: {err !r}")

            t=time.monotonic()
            if nt>t:
                await anyio.sleep(nt-t)
            else:
                logger.warn(f"{self.host} {slot}: late by {t-nt :.1f}s")
                nt = time.monotonic()
            nt += s.time


    async def poll(self, slots:set=None):
        if not slots:
            slots = self.data.slots.keys()
        async with anyio.create_task_group() as tg:
            for k in slots:
                tg.start_soon(self.poll_slot, k)
