"""
Types that describe a modbus device, as read from file
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextlib import asynccontextmanager
from copy import deepcopy
from pathlib import Path as FSPath

import anyio
from asyncscope import scope
from moat.util import CtxObj, P, Path, attrdict, combine_dict, merge, yload

from moat.modbus.typemap import get_kind, get_type2
from moat.modbus.types import Coils, DiscreteInputs, InputRegisters
from moat.modbus.server import UnitContext
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.modbus.client import ModbusClient, Slot, Unit

logger = logging.getLogger(__name__)


class BadRegisterError(ValueError):
    """Broken register description"""

    pass


class NotARegisterError(ValueError):
    """Not a register at this location"""

    pass


def mark_orig(d):
    if isinstance(d, dict):
        d._is_orig = True
        for k, v in d.items():
            if k != "default":
                mark_orig(v)


def fixup(d, this_file=None, **k):
    """
    See `fixup_`.

    Also marks original data
    """
    mark_orig(d)
    d = fixup_i(d, this_file=this_file)
    return fixup_(d, **k)


def fixup_i(d, this_file=None):
    """
    Run processing instructions: include
    """
    if isinstance(d, Mapping):
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
                inc[i] = fixup_i(dd, this_file=f)
            inc.reverse()
            d = combine_dict(d, *inc, cls=attrdict)
            d._root = True

    for k, v in d.items() if hasattr(d, "items") else enumerate(d):
        if isinstance(v, (Mapping, list, tuple)):
            d[k] = fixup_i(v)

    return d


def fixup_(
    d,
    root=None,
    path=Path(),
    post=None,
    default=None,
    offset=0,
    do_refs=True,
    apply_default=False,
):
    """
    Run processing instructions: ref, default, repeat
    """
    if root is None or getattr(d, "_root", False):
        root = d
    else:
        pass
    if default is None:
        default = attrdict()

    reps = set()

    if isinstance(d, Mapping):
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

        if "register" in d or apply_default:
            if "register" in d:
                d.register += offset
            merge(d, default, replace=False)

        # Offset is modified here
        if rep:
            k = rep.get("start", 0)
            n = rep.n
            off = offset
            while n > 0:
                v = combine_dict(d.get(k, attrdict()), deepcopy(rep.data), cls=attrdict)
                d[k] = fixup_(
                    v,
                    root,
                    path / k,
                    default=default,
                    offset=off,
                    do_refs=do_refs,
                    apply_default=getattr(d, "_apply_default", False),
                )
                reps.add(k)

                n -= 1
                k += 1
                off += rep.offset

    for k, v in d.items() if hasattr(d, "items") else enumerate(d):
        if k in reps:
            continue
        if isinstance(v, (Mapping, list, tuple)):
            d[k] = fixup_(
                v,
                root,
                path / k,
                default=default,
                offset=offset,
                do_refs=do_refs,
                apply_default=getattr(d, "_apply_default", False),
            )

    if post is not None:
        d = post(d, path)

    return d


class Register:
    """A single modbus device's register.

    This class duck-types as a moat.modbus.types.BaseValue."""

    last_gen = -1
    block = None

    def __init__(self, d, path, unit=None):
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
            if s in {"bit", "invbit"}:
                pass
            elif self.reg_type is DiscreteInputs or self.reg_type is Coils:
                raise RuntimeError(f"Coils/Discretes must be BitValue, at {path}")

        try:
            l = d.len
        except AttributeError:
            if s in {"bit", "invbit", "int", "uint"}:
                l = 1
            elif s == "float":
                l = 2
            else:
                raise BadRegisterError("no length") from None

        self.reg = get_type2(s, l)()

        self.register = d.register

        if "slot" in d and unit is not None:
            slot = unit.slot(d.slot)
            try:
                slot.add(self.reg_type, offset=self.register, cls=self.reg)
            except ValueError:
                raise ValueError("Already known", slot, self.reg_type, self.register) from None
            self.slot = slot
        self.unit = unit
        self.data = d
        self.factor = 10 ** self.data.get("scale", 0) * self.data.get("factor", 1)
        self.offset = self.data.get("offset", 0)
        self.path = path

    async def start(self):
        pass

    def __aiter__(self):
        return self._iter().__aiter__()

    async def _iter(self):
        async for val in self.reg:
            if val is not None:
                if self.factor != 1:
                    val *= self.factor
                if self.offset:
                    val += self.offset
            yield val

    @property
    def value(self):
        """Returns the factor+offset-adjusted value from the bus"""
        val = self.reg.value
        if val is not None:
            if self.factor != 1:
                val *= self.factor
            if self.offset:
                val += self.offset
        return val

    @property
    def value_w(self):
        """Returns the factor+offset-adjusted value from the bus"""
        val = self.reg.value_w
        if val is not None:
            if self.factor != 1:
                val *= self.factor
            if self.offset:
                val += self.offset
        return val

    @value.setter
    def value(self, val):
        """Sets the value that'll be written to the bus.
        Reverses factor+offset-adjustment.
        Should trigger an update.
        """
        if val is not None:
            if self.offset:
                val -= self.offset
            if self.factor != 1:
                val /= self.factor
        self.reg.set(val)

    @property
    def len(self):
        """number of Modbus registers occupied by this value"""
        return self.reg.len

    def encode(self):
        """Encode myself"""
        return self.reg.encode()

    def decode(self, regs: list[int]):
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


class BaseDevice:
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

    data: attrdict = None
    cfg: attrdict = None
    cfg_path: FSPath = None

    def __init__(self, factory=Register):
        self.factory = factory

    async def load(self, path: str | None = None, data: dict | None = None):
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

    def get(self, path: Path):
        """Fetch the register at a subpath.

        Raises an error if there's no register there.
        """
        dev = self.data._get(path)  # pylint: disable=protected-access
        if not isinstance(dev, Register):
            raise NotARegisterError(path)
        return dev


class ClientDevice(CtxObj, BaseDevice):
    """
    A client device, i.e. one that mirrors some Modbus master's unit
    """

    unit: Unit = None

    def __init__(self, client: ModbusClient, factory=Register):
        super().__init__(factory)
        self.client = client

    @asynccontextmanager
    async def _ctx(self):
        if "host" in self.cfg.src:
            host = await self.client.host_service(self.cfg.src.host, self.cfg.src.get("port"))
        else:
            host = await self.client.serial_service(
                port=self.cfg.src.port,
                **self.cfg.src.get("serial", {}),
            )
        self.unit = await host.unit_scope(self.cfg.src.unit)

        self.data = fixup(self.cfg, root=self.cfg, path=Path(), this_file=self.cfg_path)
        await self.add_slots()
        await self.add_registers()
        yield self

    async def as_scope(self):
        "Basic scope generator"
        async with self:
            scope.register(self)
            await scope.no_more_dependents()

    async def add_slots(self):
        return

    async def add_slots(self):
        """Add configured slots to this instance"""
        if "slots" not in self.data:
            logger.warning("No slots in %r", self)
            return
        for k, v in self.data.slots.items():
            if v is None:
                v = {}
            self.slots[k] = await self.unit.slot_scope(k, **v)

    async def add_registers(self):
        """Replace entries w/ register/slot members with Register instances"""

        async def a_r(d, path=Path()):
            seen = False
            for k, v in d.items():
                if not isinstance(v, dict):
                    continue
                if await a_r(v, path / k):
                    seen = True
                    if "register" in v:
                        logger.warning("%s has a sub-register: ignored", path / k)
                    elif "slot" in v:
                        logger.warning("%s is not a register", path / k)
                    continue

                if "register" in v:
                    v.setdefault("slot", "write")
                    d[k] = f = self.factory(v, path / k, self.unit)
                    await f.start()
                    seen = True
                elif "slot" in v:
                    logger.warning("%s is not a register", path / k)
            return seen

        await a_r(self.data)

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

    async def poll(self, slots: set | None = None, *, task_status=None):
        """Task to periodically poll all slots"""
        if slots is None:
            slots = self.data.slots.keys()
        for slot in slots:
            self.unit.slots[slot].start()
        if task_status is not None:
            task_status.started()

        while True:
            await anyio.sleep(99999)


class ServerDevice(BaseDevice):
    """
    A server device, i.e. a unit that's accessed via modbus.
    """

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.unit = UnitContext()

        # duck-type me
        try:
            self.validate = self.unit.validate
        except AttributeError:
            pass
        self.getValues = self.unit.getValues
        self.setValues = self.unit.setValues

    def async_getValues(self,*a,**kw):
        return self.unit.async_getValues(*a,**kw)

    def async_setValues(self,*a,**kw):
        return self.unit.async_setValues(*a,**kw)

    async def load(self, path: str | None = None, data: dict | None = None):
        await super().load(path, data)
        self.data = fixup(self.cfg, root=self.cfg, path=Path(), this_file=self.cfg_path)
        await self.add_registers()

    async def add_registers(self):
        """Replace entries w/ register/slot members with Register instances"""

        async def a_r(d, path=Path()):
            seen = False
            for k, v in d.items():
                if not isinstance(v, dict):
                    continue
                if await a_r(v, path / k):
                    seen = True
                    if "register" in v:
                        logger.warning("%s has a sub-register: ignored", path / k)
                    elif "slot" in v:
                        logger.warning("%s is not a register", path / k)
                    continue

                if "register" in v:
                    d[k] = reg = self.factory(v, path / k)
                    await reg.start()
                    self.unit.add(get_kind(v.get("reg_type")), offset=v.register, val=reg)
                    seen = True
            return seen

        await a_r(self.cfg)
