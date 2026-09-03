"""
Packet structure for diyBMS-MoaT messages
"""

from __future__ import annotations

# struct PacketHeader
# {
#  uint8_t start;
#  unsigned int _reserved:2;
#  unsigned int global:1;
#  unsigned int seen:1;
#  unsigned int command:4;
#  uint8_t hops;
#  unsigned int cells:5;
#  unsigned int sequence:3;
# } __attribute__((packed));
import logging
from dataclasses import dataclass
from enum import IntEnum
from struct import Struct

from moat.ems.battery.errors import MessageError
from moat.lib.proxy import as_proxy

from typing import ClassVar

logger = logging.getLogger(__name__)

__all__ = [
    "MAXCELLS",
    "PacketHeader",
    "PacketType",
    "ReplyBalanceCurrentCounter",
    "ReplyBalanceLevel",
    "ReplyBalancePower",
    "ReplyConfig",
    "ReplyCounters",
    "ReplyIdentify",
    "ReplyReadPIDconfig",
    "ReplyReadSettings",
    "ReplyResetBalanceCurrentCounter",
    "ReplyResetCounters",
    "ReplyTemperature",
    "ReplyTiming",
    "ReplyVoltages",
    "ReplyWritePIDconfig",
    "RequestBalanceCurrentCounter",
    "RequestBalanceLevel",
    "RequestBalancePower",
    "RequestConfig",
    "RequestCounters",
    "RequestIdentify",
    "RequestReadPIDconfig",
    "RequestReadSettings",
    "RequestResetBalanceCurrentCounter",
    "RequestResetCounters",
    "RequestTemperature",
    "RequestTiming",
    "RequestVoltages",
    "RequestWritePIDconfig",
    "replyClass",
    "requestClass",
]


MAXCELLS = 32

try:
    _dcc = dataclass(slots=True)
except TypeError:
    _dcc = dataclass()


def _dc(name):
    """Decorator: register as proxy and apply dataclass."""

    def dch(proc):
        as_proxy(f"eb_ds_{name}", proc)
        return _dcc(proc)

    return dch


class PacketType(IntEnum):
    "Type of BMS packet"

    ResetCounters = 0
    ReadVoltages = 1
    Identify = 2
    ReadTemperature = 3
    ReadCounters = 4
    ReadSettings = 5
    WriteSettings = 6
    ReadBalancePower = 7
    Timing = 8
    ReadBalanceCurrentCounter = 9
    ResetBalanceCurrentCounter = 10
    WriteBalanceLevel = 11
    WritePIDconfig = 12
    ReadPIDconfig = 13


@_dc("hdr")
class PacketHeader:
    "Packet header"

    start: int = 0
    broadcast: bool = False
    seen: bool = False
    command: int | None = None
    hops: int = 0
    cells: int = 0
    sequence: int = 0

    S: ClassVar = Struct("BBBB")
    n_seq: ClassVar = 8

    def __post_init__(self, *a, **k):
        if not isinstance(self.start, int):
            raise TypeError(self.start)

    @classmethod
    def decode(cls, msg: bytes):
        """decode a message to header + rest"""
        off = cls.S.size
        hdr = cls.from_bytes(msg[0:off])
        return hdr, memoryview(msg)[off:]

    def decode_all(self, msg: bytes) -> list[_Reply]:
        """Decode the packets described by this header.

        This method is used by the server.
        """

        assert self.command is not None
        RC = replyClass[self.command]
        pkt_len = RC.S.size
        mv = memoryview(msg)

        off = 0
        pkt = []
        if self.broadcast:
            # The request header has not been deleted,
            # so we need to skip it
            off += replyClass[self.command].S.size
        if pkt_len:
            while off < len(mv):
                if off + pkt_len > len(mv):
                    raise MessageError(bytes(mv))  # incomplete
                pkt.append(RC.from_bytes(mv[off : off + pkt_len]))
                off += pkt_len
        if off != len(mv):
            raise MessageError(bytes(mv))
        return pkt

    def encode(self):  # noqa:D102
        return self.to_bytes()

    def encode_all(self, pkt: list[_Request] | _Request, end=None):
        "encode me, plus some packets, to a message"
        if not isinstance(pkt, (list, tuple)):
            pkt = [pkt]
        pkts: list[_Request] = list(pkt)  # ty: ignore[invalid-assignment]
        if self.command is None:
            self.command = pkts[0].T
        for p in pkts:
            if self.command != p.T:
                raise ValueError("Needs same type, not %s vs %s", p.T, p)

        if self.start is None or self.broadcast:
            if len(pkts) != 1 or not self.broadcast:
                raise RuntimeError("Broadcast requires one message")
            self.cells = MAXCELLS - 1
        elif end is not None:
            self.cells = end - self.start
            if pkts[0].S.size > 0 and len(pkts) != self.cells + 1:
                raise ValueError(
                    f"Wrong packet count, {len(pkts)} vs {self.cells + 1} for {pkts[0]}"
                )
        else:
            self.cells = len(pkts) - 1
        return self.to_bytes() + b"".join(p.to_bytes() for p in pkts)

    @classmethod
    def from_bytes(cls, data):  # noqa:D102
        self = cls()
        self.start, bsc, self.hops, cs = self.S.unpack(data)
        self.broadcast = bool(bsc & 0x20)
        self.seen = bool(bsc & 0x10)
        self.command = bsc & 0x0F
        self.cells = cs >> 3
        self.sequence = cs & 0x07
        return self

    def __setstate__(self, data):
        raise NotImplementedError

    #   self.start = data.get("s", 0)
    #   self.sequence = data.get("i", None)
    #   self.cells = data.get("n", 0)
    #   self.seen = data.get("v", False)
    #   self.broadcast = data.get("bc", False)
    #   self.command = data["a"]

    def to_bytes(self):  # noqa:D102
        assert self.command is not None
        return self.S.pack(
            self.start,
            (self.broadcast << 5) | (self.seen << 4) | (self.command & 0x0F),
            self.hops,
            (self.cells << 3) | (self.sequence & 0x07),
        )

    def __getstate__(self):
        res = {"a": self.command}
        if self.sequence is not None:
            res["i"] = self.sequence
        if self.start is not None:
            res["s"] = self.start
        if self.broadcast:
            res["bc"] = True
        if self.seen:
            res["v"] = True
        if self.cells:
            res["n"] = self.cells
        if self.hops > 0:
            res["h"] = self.hops
        return res


class NullStruct:
    size = 0


class NullData:
    S: ClassVar = NullStruct

    @classmethod
    def from_bytes(cls, data):
        "Build from serialized data"
        self = cls()
        if len(data):
            raise RuntimeError("I expect empty data")
        return self

    def to_bytes(self):
        "return serialized data"
        return b""


class _Request(NullData):
    T: ClassVar = PacketType.ResetCounters

    @classmethod
    def from_cell(cls, cell: object):
        "Build from cell data"
        cell  # noqa:B018
        return cls()

    def to_bytes(self):
        "return serialized data"
        return b""

    def __setstate__(self, data):
        pass

    def __getstate__(self):
        return dict()


class _Reply(NullData):
    T: ClassVar = PacketType.ResetCounters

    @classmethod
    def from_bytes(cls, data):
        "Build from serialized data"
        self = cls()
        if len(data):
            raise RuntimeError("I expect empty data")
        return self

    def to_cell(self, cell):
        "build cell data"
        cell  # noqa:B018
        return False

    def __setstate__(self, data):
        if data:
            raise RuntimeError("I expect empty data")

    def __getstate__(self):
        return dict()


@_dc("cfg>")
class RequestConfig:  # noqa:D101
    voltageCalibration: float = 0
    bypassTempRaw: int | None = None
    bypassVoltRaw: int | None = None

    S: ClassVar = Struct("<IHH")
    T: ClassVar = PacketType.WriteSettings

    @classmethod
    def from_cell(cls, cell):  # noqa:D102
        self = cls()
        self.voltageCalibration = cell.v_calibration
        self.bypassTempRaw = cell.load_maxtemp_raw
        self.bypassVoltRaw = cell.balance_config_threshold_raw
        return self

    def to_bytes(self):  # noqa:D102
        vc = int(self.voltageCalibration)
        return self.S.pack(vc, self.bypassTempRaw or 0, self.bypassVoltRaw or 0)

    def __setstate__(self, data):
        self.voltageCalibration = data["vc"]
        self.bypassTempRaw = data["tr"]
        self.bypassVoltRaw = data["vr"]

    def __getstate__(self):
        return dict(vc=self.voltageCalibration, tr=self.bypassTempRaw, vr=self.bypassVoltRaw)


@_dc("pidc>")
class RequestWritePIDconfig:  # noqa:D101
    p: int | None = None
    i: int | None = None
    d: int | None = None

    S: ClassVar = Struct("<III")
    T: ClassVar = PacketType.WritePIDconfig

    def to_bytes(self):  # noqa:D102
        return self.S.pack(self.kp, self.ki, self.kd)

    def __setstate__(self, data):
        self.kp = data["p"]
        self.ki = data["i"]
        self.kd = data["d"]

    def __getstate__(self):
        return dict(p=self.kp, i=self.ki, d=self.kd)


@_dc("v<")
class ReplyVoltages(_Reply):  # noqa:D101
    voltRaw: int | None = None
    bypassRaw: int | None = None

    S: ClassVar = Struct("<HH")
    T: ClassVar = PacketType.ReadVoltages

    @classmethod
    def from_bytes(cls, data):  # noqa:D102
        self = cls()
        self.voltRaw, self.bypassRaw = self.S.unpack(data)
        return self

    def to_cell(self, cell):  # noqa:D102
        cell.m_volt(self)

    def __setstate__(self, data):
        self.voltRaw = data["vr"]
        if data.get("bal", False):
            self.voltRaw |= 0x8000
        if data.get("ot", False):
            self.voltRaw |= 0x4000
        # self.bypassRaw = data["br"]

    def __getstate__(self):
        assert self.voltRaw is not None
        m = dict(vr=self.voltRaw & 0x1FFF)
        # if self.bypassRaw:
        #     m["br"] = self.bypassRaw
        if self.voltRaw & 0x8000:
            m["bal"] = True
        if self.voltRaw & 0x4000:
            m["ot"] = True
        return m


@_dc("tm<")
class ReplyTemperature(_Reply):  # noqa:D101
    intRaw: int | None = None
    extRaw: int | None = None

    S: ClassVar = Struct("BBB")
    T: ClassVar = PacketType.ReadTemperature

    @classmethod
    def from_bytes(cls, data):  # noqa:D102
        self = cls()
        b1, b2, b3 = self.S.unpack(data)
        self.intRaw = b1 | ((b2 & 0x0F) << 8)
        self.extRaw = (b2 >> 4) | (b3 << 4)
        return self

    def to_cell(self, cell):  # noqa:D102
        cell.m_temp(self)

    def __setstate__(self, data):
        self.intRaw = data.get("ir", None)
        self.extRaw = data.get("er", None)

    def __getstate__(self):
        m = {}
        if self.intRaw:
            m["ir"] = self.intRaw
        if self.extRaw:
            m["er"] = self.extRaw
        return m


@_dc("c<")
class ReplyCounters(_Reply):  # noqa:D101
    received: int | None = None
    bad: int | None = None

    S: ClassVar = Struct("<HH")
    T: ClassVar = PacketType.ReadCounters

    @classmethod
    def from_bytes(cls, data):  # noqa:D102
        self = cls()
        self.received, self.bad = self.S.unpack(data)
        return self

    def to_cell(self, cell):  # noqa:D102
        cell.packets_in = self.received
        cell.packets_bad = self.bad

    def __setstate__(self, data):
        self.received = data.get("nr", 0)
        self.bad = data.get("nb", 0)

    def __getstate__(self):
        return dict(nr=self.received, nb=self.bad)


@_dc("set<")
class ReplyReadSettings(_Reply):  # noqa:D101
    gitVersion: int | None = None
    boardVersion: int | None = None
    dataVersion: int | None = None
    mvPerADC: int | None = None

    voltageCalibration: float = 0
    bypassTempRaw: int | None = None
    bypassVoltRaw: int | None = None
    BCoeffInternal: int | None = None
    BCoeffExternal: int | None = None
    numSamples: int | None = None
    loadResRaw: int | None = None

    S: ClassVar = Struct("<LHBBfHHHHBB")
    T: ClassVar = PacketType.ReadSettings

    @classmethod
    def from_bytes(cls, data):  # noqa:D102
        self = cls()
        (
            self.gitVersion,
            self.boardVersion,
            self.dataVersion,
            self.mvPerADC,
            self.voltageCalibration,
            self.bypassTempRaw,
            self.bypassVoltRaw,
            self.BCoeffInternal,
            self.BCoeffExternal,
            self.numSamples,
            self.loadResRaw,
        ) = self.S.unpack(data)
        return self

    def __setstate__(self, data):
        self.gitVersion = data.get("gitV", None)
        self.boardVersion = data.get("hwV", None)
        self.dataVersion = data.get("dataV", None)
        self.mvPerADC = data.get("mvStep", None)
        self.voltageCalibration = data.get("vCal", None)
        self.bypassTempRaw = data.get("byTR", None)
        self.bypassVoltRaw = data.get("byVR", None)
        self.BCoeffInternal = data.get("bci", None)
        self.BCoeffExternal = data.get("bce", None)
        self.numSamples = data.get("nS", None)
        self.loadResRaw = data.get("lR", None)

    def __getstate__(self):
        return dict(
            gitV=self.gitVersion,
            hwV=self.boardVersion,
            dataV=self.dataVersion,
            mvStep=self.mvPerADC,
            vCal=self.voltageCalibration,
            byTR=self.bypassTempRaw,
            byVR=self.bypassVoltRaw,
            bci=self.BCoeffInternal,
            bce=self.BCoeffExternal,
            nS=self.numSamples,
            lR=self.loadResRaw,
        )


@_dc("ti<")
class RequestTiming:  # noqa:D101
    timer: int | None = None

    S: ClassVar = Struct("<H")
    T: ClassVar = PacketType.Timing

    @classmethod
    def from_bytes(cls, data):  # noqa:D102
        self = cls()
        (self.timer,) = self.S.unpack(data)
        return self

    def to_bytes(self):  # noqa:D102
        assert self.timer is not None
        return self.S.pack(self.timer & 0xFFFF)

    def __setstate__(self, data):
        self.timer = data.get("t", None)

    def __getstate__(self):
        return dict(t=self.timer)


@_dc("ti>")
class ReplyTiming(RequestTiming):  # noqa:D101
    pass


@_dc("bcc<")
class ReplyBalanceCurrentCounter(_Reply):  # noqa:D101
    counter: int | None = None

    S: ClassVar = Struct("<I")
    T: ClassVar = PacketType.ReadBalanceCurrentCounter

    @classmethod
    def from_bytes(cls, data):  # noqa:D102
        self = cls()
        (self.counter,) = self.S.unpack(data)
        return self

    def to_cell(self, cell):  # noqa:D102
        cell.balance_current_count = self.counter

    def __setstate__(self, data):
        self.cmounter = data["c"]

    def __getstate__(self):
        return dict(c=self.counter)


@_dc("pid<")
class ReplyReadPIDconfig(_Reply):  # noqa:D101
    kp: int | None = None
    ki: int | None = None
    kd: int | None = None

    S: ClassVar = Struct("<III")
    T: ClassVar = PacketType.ReadPIDconfig

    @classmethod
    def from_bytes(cls, data):  # noqa:D102
        self = cls()
        self.kp, self.ki, self.kd = self.S.unpack(data)
        return self

    def to_cell(self, cell):  # noqa:D102
        cell.m_pid(self)

    def __setstate__(self, data):
        self.kp = data["p"]
        self.ki = data["i"]
        self.kd = data["d"]

    def __getstate__(self):
        return dict(p=self.kp, i=self.ki, d=self.kd)


@_dc("bal>")
class RequestBalanceLevel:  # noqa:D101
    levelRaw: int | None = None

    S: ClassVar = Struct("<H")
    T: ClassVar = PacketType.WriteBalanceLevel

    async def from_cell(self, cell):  # noqa:D102
        await cell.bal()
        await cell.v2raw()

        self.levelRaw = cell.balance_threshold_raw

    def to_bytes(self):  # noqa:D102
        return self.S.pack(self.levelRaw or 0)

    def __setstate__(self, data):
        self.levelRaw = data["lR"]

    def __getstate__(self):
        return dict(lR=self.levelRaw)


@_dc("bal<")
class ReplyBalancePower(_Reply):  # noqa:D101
    pwm: int | None = None

    S: ClassVar = Struct("B")
    T: ClassVar = PacketType.ReadBalancePower

    @classmethod
    def from_bytes(cls, data):  # noqa:D102
        self = cls()
        (self.pwm,) = self.S.unpack(data)
        return self

    def to_cell(self, cell):  # noqa:D102
        chg = False
        assert self.pwm is not None
        pwm = self.pwm / 255
        if cell.balance_pwm != pwm:
            chg = True
            cell.balance_pwm = pwm
        return chg

    def __setstate__(self, data):
        self.pwm = data["r"]

    def __getstate__(self):
        return dict(r=self.pwm)


@_dc("set>")
class RequestReadSettings(_Request):  # noqa:D101
    T = PacketType.ReadSettings


@_dc("ct>")
class RequestTemperature(_Request):  # noqa:D101
    T = PacketType.ReadTemperature


@_dc("bcc>")
class RequestBalanceCurrentCounter(_Request):  # noqa:D101
    T = PacketType.ReadBalanceCurrentCounter


@_dc("pc>")
class RequestCounters(_Request):  # noqa:D101
    T = PacketType.ReadCounters


@_dc("bp>")
class RequestBalancePower(_Request):  # noqa:D101
    T = PacketType.ReadBalancePower


@_dc("rpc>")
class RequestResetCounters(_Request):  # noqa:D101
    T = PacketType.ResetCounters


@_dc("rpcc>")
class RequestResetBalanceCurrentCounter(_Request):  # noqa:D101
    T = PacketType.ResetBalanceCurrentCounter


@_dc("cv>")
class RequestVoltages(_Request):  # noqa:D101
    T = PacketType.ReadVoltages


@_dc("id>")
class RequestIdentify(_Request):  # noqa:D101
    T = PacketType.Identify


@_dc("rpid>")
class RequestReadPIDconfig(_Request):  # noqa:D101
    T = PacketType.ReadPIDconfig


@_dc("cfg<")
class ReplyConfig(_Reply):  # noqa:D101
    T = PacketType.WriteSettings


@_dc("rbcc<")
class ReplyResetBalanceCurrentCounter(_Reply):  # noqa:D101
    T = PacketType.ResetBalanceCurrentCounter


@_dc("rpc<")
class ReplyResetCounters(_Reply):  # noqa:D101
    T = PacketType.ResetCounters


@_dc("bl<")
class ReplyBalanceLevel(_Reply):  # noqa:D101
    T = PacketType.WriteBalanceLevel


@_dc("id<")
class ReplyIdentify(_Reply):  # noqa:D101
    T = PacketType.Identify


@_dc("wpid<")
class ReplyWritePIDconfig(_Reply):  # noqa:D101
    T = PacketType.WritePIDconfig


requestClass = [
    RequestResetCounters,  # ResetCounters=0
    RequestVoltages,  # ReadVoltages=1
    RequestIdentify,  # Identify=2
    RequestTemperature,  # ReadTemperature=3
    RequestCounters,  # ReadCounters=4
    RequestReadSettings,  # ReadSettings=5
    RequestConfig,  # WriteSettings=6
    RequestBalancePower,  # ReadBalancePower=7
    RequestTiming,  # Timing=8
    RequestBalanceCurrentCounter,  # ReadBalanceCurrentCounter=9
    RequestResetBalanceCurrentCounter,  # ResetBalanceCurrentCounter=10
    RequestBalanceLevel,  # WriteBalanceLevel=11
    RequestWritePIDconfig,  # 12
    RequestReadPIDconfig,  # 13
    NullData,  # 14
    NullData,  # 15
]

replyClass = [
    ReplyResetCounters,  # ResetCounters=0
    ReplyVoltages,  # ReadVoltages=1
    ReplyIdentify,  # Identify=2
    ReplyTemperature,  # ReadTemperature=3
    ReplyCounters,  # ReadCounters=4
    ReplyReadSettings,  # ReadSettings=5
    ReplyConfig,  # WriteSettings=6
    ReplyBalancePower,  # ReadBalancePower=7
    ReplyTiming,  # Timing=8
    ReplyBalanceCurrentCounter,  # ReadBalanceCurrentCounter=9
    ReplyResetBalanceCurrentCounter,  # ResetBalanceCurrentCounter=10
    ReplyBalanceLevel,  # WriteBalanceLevel=11
    ReplyWritePIDconfig,  # 12
    ReplyReadPIDconfig,  # 13
    NullData,  # 14
    NullData,  # 15
]
