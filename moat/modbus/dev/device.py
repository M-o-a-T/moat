"""
Types that describe a modbus device, as read from file
"""

import logging
import time
from collections.abc import Mapping
from pathlib import Path as FSPath
from typing import List
from contextlib import asynccontextmanager
from copy import deepcopy

import anyio
from asyncscope import scope
from moat.util import CtxObj, P, Path, attrdict, combine_dict, merge, yload

from ..client import Host, ModbusClient, ModbusError, Slot, Unit
from ..typemap import get_kind, get_type2
from ..types import Coils, DiscreteInputs, InputRegisters

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
            v = combine_dict(d.get(k, attrdict()), deepcopy(rep.data), cls=attrdict)
            d[k] = fixup(
                v,
                root,
                path / k,
                default=default,
                offset=off,
                do_refs=do_refs,
                this_file=this_file,
            )
            reps.add(k)

            n -= 1
            k += 1
            off += rep.offset

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
    block = None

    def __init__(self, d, path, unit):
        try:
            self.reg_type = get_kind(d.reg_type)
        except AttributeError:
            self.reg_type = InputRegisters

        try:
            s = d.type
        except AttributeError:
            if self.reg_type is DiscreteInputs or self.reg_type is Coils:
                s = "bit"
            else:
                raise AttributeError(f"No type in {path}") from None
        else:
            if s == "bit":
                if not (self.reg_type is DiscreteInputs or self.reg_type is Coils):
                    raise RuntimeError(f"Only Coils/Discretes can be BitValue, at {path}")
            elif self.reg_type is DiscreteInputs or self.reg_type is Coils:
                raise RuntimeError(f"Coils/Discretes must be BitValue, at {path}")

        try:
            l = d.len
        except AttributeError:
            if s in {"bit", "int", "uint"}:
                l = 1
            elif s == "float":
                l = 2
            else:
                raise BadRegisterError("no length") from None

        self.reg = get_type2(s, l)()

        self.register = d.register

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
        """Set the value, reverse factor+offset-adjustment. May trigger an update."""
        if val is not None:
            val = (val - self.offset) / self.factor
        self.reg.set(val)

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


class Device(CtxObj):
    """A modbus device.

    The idea is to use the device description file as a template.

    You augment that file with "slot" data, i.e. named intervals,
    plus processing instructions. The instructions may contain slot names.

    For each slot, the system will periodically fetch the data and call a
    given postprocessor for each item, which can e.g. forward the value to
    MQTT.

    @factory is used to create bus registers. Used to augment basic
    registers, e.g. with different storage backends.
    """

    host: Host = None
    data: attrdict = None
    unit: Unit = None
    cfg: attrdict = None
    cfg_path: FSPath = None

    def __init__(self, client: ModbusClient, factory=Register):
        self.client = client
        self.factory = factory

    def load(self, path: str = None, data: dict = None):
        """Load a device description from @path, augmented by @data"""
        if self.cfg is not None:
            raise RuntimeError("already called")

        if path is None:
            d = attrdict()
        else:
            path = _data / path
            d = yload(path, attr=True)
        if data is not None:
            d = merge(d, data)
        self.cfg = d
        self.cfg_path = path


    @asynccontextmanager
    async def _ctx(self):
        if "host" in self.data.src:
            host = await self.client.host_service(self.data.src.host, self.data.src.get("port"))
        else:
            host = await self.client.serial_service(
                self.data.src.port, **self.data.src.get("serial,", {})
            )
        self.unit = await host.unit_service(self.data.src.unit)
        self.data = fixup(self.cfg, self.cfg, Path(), this_file=self.cfg_path)
        await self.add_slots()
        self.add_registers()
        yield self

    async def as_scope(self):
        async with self:
            scope.register(self)
            await scope.no_more_dependents()

    async def add_slots(self, keys):
        for k,v in elf.data.slots.items():
            self.slots[k] = await scope.service(f"MDS:{id(self)}:{k}", self.unit.slot_service, **v)

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

                if "register" in v:
                    d[k] = reg = self.factory(v, path / k, self.unit)
                    s = v.get("slot", "write")
                    sl = self.slots.get(s, None)
                    if sl is not None:
                        reg.block = sl
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
        vals = await slot.read()
        if proc is not None:
            async with anyio.create_task_group() as tg:
                for d in vals.values():
                    for v in d.values():
                        tg.start_soon(proc, v)
        return vals

    async def poll_slot(self, slot: str, *, task_status=None):
        """Task to register and periodically poll a given slot"""
        # slots:
        #  1sec:
        #    time: 1
        #    align: false
        #
        # align=True: wait for the next multiple
        # align=False: fetch now, *then* wait for the next multiple
        # align=None: fetch now, wait for the timespan

        if task_status is not None:
            task_status.started()

        sl = self.unit.slots[slot]
        sl.start()
        
        while True:
            await anyio.sleep(99999)

    async def poll(self, slots: set = None, *, task_status=None):
        """Task to periodically poll all slots"""
        if slots is None:
            slots = self.data.slots.keys()
        for slot in slots:
            self.unit.slots[slot].start()
        if task_status is not None:
            task_status.started()

        while True:
            await anyio.sleep(99999)
