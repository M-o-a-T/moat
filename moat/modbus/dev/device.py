"""
Types that describe a modbus device, as read from file
"""

import logging
import time
from collections.abc import Mapping
from pathlib import Path as FSPath
from typing import List

import anyio
from moat.util import P, Path, attrdict, combine_dict, merge, yload

from ..client import Host, ModbusClient, Slot, Unit
from ..typemap import get_kind, get_type2
from ..types import InputRegisters

logger = logging.getLogger(__name__)


class BadRegisterError(ValueError):
    """Broken register description"""

    pass


class NotARegisterError(ValueError):
    """Not a register at this location"""

    pass


def fixup(
    d, root=None, path=Path(), post=None, default=None, offset=0, do_refs=True, this_file=None
):
    """
    Run processing instructions: include, ref, default, repeat
    """
    if root is None:
        root = d
        set_root = True
    else:
        set_root = root is d
    if default is None:
        default = attrdict()

    try:
        inc = d.pop("include")
    except KeyError:
        pass
    else:
        if isinstance(inc, tuple):
            inc = list(inc)
        elif not isinstance(inc, list):
            inc = [inc]
        for i, dd in enumerate(inc):
            try:
                f = _data / dd
                df = f.open("r")
            except FileNotFoundError:
                f = this_file.parent / dd
                df = f.open("r")
            with df:
                dd = yload(df, attr=True)
            inc[i] = fixup(
                dd, None, Path(), default=default, offset=offset, do_refs=do_refs, this_file=f
            )
        inc.reverse()
        d = combine_dict(d, *inc, cls=attrdict)
        if set_root:
            root = d

    try:
        defs = d.pop("default")
    except KeyError:
        pass
    else:
        default = combine_dict(defs, default, cls=attrdict)

    if do_refs:
        try:
            refs = d.pop("ref")
        except KeyError:
            pass
        else:
            if isinstance(refs, str):
                refs = P(refs)
            if isinstance(refs, Path):
                refs = [refs]
            for i, p in enumerate(refs):
                refs[i] = root._get(p)  # pylint: disable=protected-access

            refs.reverse()
            d = combine_dict(d, *refs, cls=attrdict)

    try:
        rep = d.pop("repeat")
    except KeyError:
        rep = None

    if "register" in d:
        d.register += offset
        merge(d, default, replace=False)

    # Offset is modified here
    reps = set()
    if rep:
        k = rep.get("start", 0)
        n = rep.n
        off = offset
        while n > 0:
            v = combine_dict(d.get(k, attrdict()), rep.data, cls=attrdict)
            d[k] = fixup(
                v,
                root,
                path / k,
                default=default if k in d else attrdict(),
                offset=off,
                do_refs=do_refs,
                this_file=this_file,
            )
            n -= 1
            k += 1
            off += rep.offset
            reps.add(k)

    for k, v in d.items():
        if k in reps:
            continue
        if isinstance(v, Mapping):
            d[k] = fixup(
                v,
                root,
                path / k,
                default=default,
                offset=offset,
                do_refs=do_refs,
                this_file=this_file,
            )

    if post is not None:
        d = post(d, path)

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
            if s in {"int", "uint"}:
                l = 1
            elif s == "float":
                l = 2
            else:
                raise BadRegisterError("no length") from None

        self.reg = get_type2(s, l)()

        self.register = d.register
        try:
            self.reg_type = get_kind(d.reg_type)
        except AttributeError:
            self.reg_type = InputRegisters

        if "slot" in d:
            slot = unit.slot(d.slot)
            slot.add(self.reg_type, offset=self.register, cls=self.reg)
            self.slot = slot
        self.unit = unit
        self.data = d
        self.factor = 10 ** self.data.get("scale", 0) * self.data.get("factor", 1)
        self.offset = self.data.get("offset", 0)
        self.path = path

    def __aiter__(self):
        return self._iter().__aiter__()

    async def _iter(self):
        async for val in self.reg:
            if val is None:
                yield val
            else:
                yield val * self.factor + self.offset

    @property
    def value(self):
        """Return the factor+offset-adjusted value"""
        val = self.reg.value
        if val is not None:
            val = val * self.factor + self.offset
        return val

    @value.setter
    def value(self, val):
        """Set the value, reverse factor+offset-adjustment"""
        if val is not None:
            val = (val - self.offset) / self.factor
        self.reg.value = val

    @property
    def len(self):
        """number of Modbus registers occupied by this value"""
        return self.reg.len

    def encode(self):
        """Encode myself"""
        return self.reg.encode()

    def decode(self, regs: List[int]):
        """Encode registers into self"""
        self.reg.decode(regs)

    @property
    def changed(self):
        """Flag whether this register needs to be updated"""
        return self.reg.changed

    @property
    def gen(self):
        """Generation number for the current value"""
        return self.reg.gen

    def __repr__(self):
        return f"‹{str(self.reg_type)[0].lower()}{self.register} @{self.path}:{self.value}›"

    __str__ = __repr__


_data = FSPath(__file__).parent / "_data"


class Device:
    """A modbus device.

    The idea is to use the device description file as a template.

    You augment that file with "slot" data, i.e. named intervals,
    plus processing instructions. The instructions may contain slot names.

    For each slot, you periodically call `await dev.update(slotname,
    processor)`. The system will fetch the data, call a given postprocessor
    for each item (which might forward the value to MQTT), and return
    the list of registers.

    @factory is used to create bus registers. Used to augment basic
    registers, e.g. with different storage backends.
    """

    host: Host = None
    data: attrdict = None
    unit: Unit = None

    def __init__(self, client: ModbusClient, factory=Register):
        self.client = client
        self.factory = factory

    def load(self, path: str = None, data: dict = None):
        """Load a device description from @path, augmented by @data"""
        if path is None:
            d = attrdict()
        else:
            path = _data / path
            d = yload(path, attr=True)
        if data is not None:
            d = merge(d, data)
        self.data = fixup(d, d, Path(), this_file=path)

        self.host = self.client.host(self.data.src.host, self.data.src.get("port"))
        self.unit = self.host.unit(self.data.src.unit)
        self.add_registers()

    def add_registers(self):
        """Replace entries w/ register/slot members with Register instances"""

        def a_r(d, path=Path()):
            seen = False
            for k, v in d.items():
                if not isinstance(v, dict):
                    continue
                if a_r(v, path / k):
                    seen = True
                    if "register" in v:
                        logger.warning("%s has a sub-register: ignored", path / k)
                        continue
                    continue

                if "register" in v:
                    d[k] = self.factory(v, path / k, self.unit)
                    seen = True
                elif "slot" in v:
                    logger.warning("%s is not a register", path / k)
            return seen

        a_r(self.data)

    def get(self, path: Path):
        """Fetch the register at a subpath.

        Raises an error if there's no register there.
        """
        dev = self.data._get(path)  # pylint: disable=protected-access
        if not isinstance(dev, Register):
            raise NotARegisterError(path)
        return dev

    @property
    def slots(self):
        """The slots of this unit"""
        return self.unit.slots

    async def update(self, slot: Slot, proc=None):
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
        # slots:
        #  1sec:
        #    time: 1
        #    align: false
        #
        # align=True: wait for the next multiple
        # align=False: fetch now, *then* wait for the next multiple
        # align=None: fetch now, wait for the timespan
        s = self.data.slots[slot]
        sl = self.unit.slot(slot)
        al = s.get("align", None)
        if al is not None:
            t = time.time()
            r = (-t) % s.time
            if al:
                await anyio.sleep(r)
        nt = time.monotonic()

        backoff = s.time / 10
        while True:
            try:
                await self.update(sl)
            except Exception as err:  # pylint: disable=broad-except
                e = (
                    logger.error
                    if isinstance(err, (ModbusError, anyio.EndOfStream))
                    else logger.exception
                )
                e("%s: %r: wait %s", sl, err, backoff)
                await anyio.sleep(backoff)
                backoff = min(max(s.time * 2, 60), backoff * 1.2)
                continue
            else:
                backoff = s.time / 10

            t = time.monotonic()
            if nt > t:
                await anyio.sleep(nt - t)
            else:
                if al:
                    nnt = nt + s.time * int(t - nt)  # +1 added below
                else:
                    nnt = time.monotonic()
                if s.time >= 5 and t - nt > s.time / 10:
                    logger.warning("%s: late by %1fs: now %s", sl, t - nt, nnt)
                nt = nnt
            nt += s.time

    async def poll(self, slots: set = None):
        """Periodically poll all slots"""
        if not slots:
            slots = self.data.slots.keys()
        async with anyio.create_task_group() as tg:
            for k in slots:
                tg.start_soon(self.poll_slot, k)
