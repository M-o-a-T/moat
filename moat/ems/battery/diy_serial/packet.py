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
from struct import Struct, pack, unpack
from typing import ClassVar

from moat.util import as_proxy
from ..errors import MessageError

logger = logging.getLogger(__name__)

__all__ = [
    "PacketType",
    "PacketHeader",
    "requestClass",
    "replyClass",
    "MAXCELLS",
]
# more exports added at the end

MAXCELLS = 32

try:
    _dcc = dataclass(slots=True)
except TypeError:
    _dcc = dataclass()

def _dc(name):
    def dch(proc):
        as_proxy(f"eb_ds_{name}", proc)
        return _dcc(proc)
    return dch


class PacketType(IntEnum):
    ResetPacketCounters = 0
    ReadVoltageAndStatus = 1
    Identify = 2
    ReadTemperature = 3
    ReadPacketCounters = 4
    ReadSettings = 5
    WriteSettings = 6
    ReadBalancePowerPWM = 7
    Timing = 8
    ReadBalanceCurrentCounter = 9
    ResetBalanceCurrentCounter = 10
    WriteBalanceLevel = 11
    WritePIDconfig = 12
    ReadPIDconfig = 13


@_dc("hdr")
class PacketHeader:
    start: int = 0
    broadcast: bool = False
    seen: bool = False
    command: int = None
    hops: int = 0
    cells: int = 0
    sequence: int = 0

    S: ClassVar = Struct("BBBB")
    n_seq: ClassVar = 8

    @classmethod
    def decode(cls, msg:bytes):
        """decode a message to header + rest"""
        off = cls.S.size
        hdr = cls.from_bytes(msg[0:off])
        return hdr, memoryview(msg)[off:]

    def decode_all(self, msg:bytes) -> list[_Reply]:
        """Decode the packets described by this header.

        This method is used by the server.
        """

        RC = replyClass[self.command]
        pkt_len = RC.S.size
        msg = memoryview(msg)

        off = 0
        pkt = []
        if hdr.broadcast:
            # The request header has not been deleted,
            # so we need to skip it
            off += requestClass[self.command].S.size
        if pkt_len:
            while off < len(msg):
                if off + pkt_len > len(msg):
                    raise MessageError(msg)  # incomplete
                pkt.append(RC.from_bytes(msg[off : off + pkt_len]))
                off += RCL
        if off != len(msg):
            raise MessageError(msg)
        return pkt


    def decode_one(self, msg):
        """Decode a single message to packet + rest.

        This method is used by the client.
        """
        off = 0
        RC = replyClass[self.command]
        pkt_len = RC.S.size
        pkt = None
        if pkt_len:
            if off + pkt_len > len(msg):
                raise MessageError(msg)  # incomplete
            pkt = RC.from_bytes(msg[off : off + pkt_len])
            if not self.broadcast:
                off += pkt_len
        if off:
            msg = memoryview(msg)[off:]
        return pkt, msg

    def encode(self):
        return self.to_bytes()

    def encode_one(self, msg, pkt):
        return self.to_bytes()+msg+(pkt.to_bytes() if pkt is not None else None)

    def encode_all(self, pkt, end=None):
        "encode me, plus some packets, to a message"
        if not isinstance(pkt, (list, tuple)):
            pkt = (pkt,)
        if self.command is None:
            self.command = pkt[0].T
        for p in pkt:
            if p.T != self.command:
                raise ValueError("Needs same type, not %s vs %s", p.T, p)

        if self.start is None or self.broadcast:
            if len(pkt) != 1 or not self.broadcast:
                raise RuntimeError("Broadcast requires one message")
            self.cells = MAXCELLS - 1
        elif end is not None:
            self.cells = end - self.start
            if pkt[0].S.size > 0 and len(pkt) != self.cells + 1:
                raise ValueError(
                    "Wrong packet count, %d vs %d for %s" % (len(pkt), self.cells + 1, pkt[0])
                )
        else:
            self.cells = len(pkt) - 1
        return self.to_bytes() + b"".join(p.to_bytes() for p in pkt)


    @classmethod
    def from_bytes(cls, data):
        self = cls()
        self.start, bsc, self.hops, cs = self.S.unpack(data)
        self.broadcast = bool(bsc & 0x20)
        self.seen = bool(bsc & 0x10)
        self.command = bsc & 0x0F
        self.cells = cs >> 3
        self.sequence = cs & 0x07
        return self

    def __setstate__(self, data):
        self.start = data.get("s", 0)
        self.sequence = data.get("i", None)
        self.cells = data.get("n", 0)
        self.seen = data.get("v", False)
        self.broadcast = data.get("bc", False)
        self.command = data["a"]

    def to_bytes(self):
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


class FloatUint:
    f = 0
    u = 0

    @classmethod
    def F(cls, val):
        self = cls()
        self.f = val
        self.u = unpack("<I", pack("f", val))[0]
        return self

    @classmethod
    def U(cls, val):
        self = cls()
        self.u = val
        self.f = unpack("f", pack("<I", val))[0]
        return self

    def __repr__(self):
        return f"‹FU {self.f}›"


class NullStruct:
    size = 0


class NullData:
    S: ClassVar = NullStruct


class _Request(NullData):
    @classmethod
    def from_cell(cls, cell):
        return cls()

    def to_bytes(self):
        return b''

    def __setstate__(self, m):
        pass

class _Reply(NullData):
    @classmethod
    def from_bytes(cls, data):
        self = cls()
        if len(data):
            raise RuntimeError("I expect empty data")
        return self

    def to_cell(self, cell):
        return False

    def __setstate__(self, data):
        if data:
            raise RuntimeError("I expect empty data")

    def __getstate__(self):
        return dict()

@_dc("cfg>")
class RequestConfig:
    voltageCalibration: FloatUint = FloatUint.U(0)
    bypassTempRaw: int = None
    bypassVoltRaw: int = None

    S: ClassVar = Struct("<IHH")
    T: ClassVar = PacketType.WriteSettings

    @classmethod
    def from_cell(cls, cell):
        self = cls()
        self.voltageCalibration = FloatUint.F(cell.v_calibration)
        self.bypassTempRaw = cell.load_maxtemp_raw
        self.bypassVoltRaw = cell.balance_config_threshold_raw
        return self

    def to_bytes(self):
        vc = self.voltageCalibration.u
        return self.S.pack(vc, self.bypassTempRaw or 0, self.bypassVoltRaw or 0)

    def __setstate__(self, m):
        self.voltageCalibration = m["vc"]
        self.bypassTempRaw = m["tr"]
        self.bypassVoltRaw = m["vr"]

    def __getstate__(self):
        return dict(vc=self.voltageCalibration, tr=self.bypassTempRaw, vr=self.bypassVoltRaw)

@_dc("pidc>")
class RequestWritePIDconfig:
    kp: int = None
    ki: int = None
    kd: int = None

    S: ClassVar = Struct("<III")
    T: ClassVar = PacketType.WritePIDconfig

    @classmethod
    def from_cell(cls, cell):
        self = cls()
        self.kp = cell.pid_kp
        self.ki = cell.pid_ki
        self.kd = cell.pid_kd
        return self

    def to_bytes(self):
        return self.S.pack(self.kp, self.ki, self.kd)

    def __setstate__(self, m):
        self.kp = m["p"]
        self.ki = m["i"]
        self.kd = m["d"]

    def __getstate__(self):
        return dict(p=self.kp, i=self.ki, d=self.kd)

@_dc("v<")
class ReplyVoltages(_Reply):
    voltRaw: int = None
    bypassRaw: int = None

    S: ClassVar = Struct("<HH")
    T: ClassVar = PacketType.ReadVoltageAndStatus

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        self.voltRaw, self.bypassRaw = self.S.unpack(data)
        return self

    def to_cell(self, cell):
        chg = False

        if cell.in_balance != bool(self.voltRaw & 0x8000):
            chg = True
            cell.in_balance = not cell.in_balance
        if cell.balance_over_temp != bool(self.voltRaw & 0x4000):
            chg = True
            cell.balance_over_temp = not cell.balance_over_temp
        vRaw = self.voltRaw & 0x1FFF
        if vRaw:
            v = cell._raw2volt(vRaw)
            if cell.voltage != v:
                chg = True
                cell.voltage = v
            cell.valid = True
        return chg

    def to_bytes(self):
        return self.S.pack(self.voltRaw, self.bypassRaw)

    def __setstate__(self, m):
        self.voltRaw = m["vr"]
        if m.get("bal", False):
            self.voltRaw |= 0x8000
        if m.get("ot", False):
            self.voltRaw |= 0x4000
        self.bypassRaw = m["br"]

    def __getstate__(self):
        m=dict(vr=self.voltRaw&0x1FFF)
        if self.bypassRaw:
            m["br"] = self.bypassRaw
        if self.voltRaw & 0x8000:
            m["bal"] = True
        if self.voltRaw & 0x4000:
            m["ot"] = True
        return m

@_dc("t<")
class ReplyTemperature(_Reply):
    intRaw: int = None
    extRaw: int = None

    S: ClassVar = Struct("BBB")
    T: ClassVar = PacketType.ReadTemperature

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        b1, b2, b3 = self.S.unpack(data)
        self.intRaw = b1 | ((b2 & 0x0F) << 8)
        self.extRaw = (b2 >> 4) | (b3 << 4)
        return self

    def to_cell(self, cell):
        chg = False
        if cell.internal_temp_raw != self.intRaw:
            chg = True
            cell.internal_temp_raw = self.intRaw
        if cell.external_temp_raw != self.extRaw:
            chg = True
            cell.external_temp_raw = self.extRaw
        return chg

    def __setstate__(self, m):
        self.intRaw = m.get("ir", None)
        self.extRaw = m.get("er", None)

    def __getstate__(self):
        m = {}
        if self.intRaw:
            m["ir"] = self.intRaw
        if self.extRaw:
            m["er"] = self.extRaw
        return m


@_dc("c<")
class ReplyCounters(_Reply):
    received: int = None
    bad: int = None

    S: ClassVar = Struct("<HH")
    T: ClassVar = PacketType.ReadPacketCounters

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        self.received, self.bad = self.S.unpack(data)
        return self

    def to_cell(self, cell):
        chg = False
        if cell.packets_in != self.received:
            chg = True
            cell.packets_in = self.received
        if cell.packets_bad != self.bad:
            chg = True
            cell.packets_bad = self.bad
        return chg

    def __setstate__(self, m):
        self.received = m.get("nr", 0)
        self.bad = m.get("nb", 0)

    def __getstate__(cls):
        return dict(nr=self.received, nb=self.bad)

@_dc("set<")
class ReplySettings(_Reply):
    gitVersion: int = None
    boardVersion: int = None
    dataVersion: int = None
    mvPerADC: int = None

    voltageCalibration: FloatUint = FloatUint.U(0)
    bypassTempRaw: int = None
    bypassVoltRaw: int = None
    BCoeffInternal: int = None
    BCoeffExternal: int = None
    numSamples: int = None
    loadResRaw: int = None

    S: ClassVar = Struct("<LHBBLHHHHBB")
    T: ClassVar = PacketType.ReadSettings

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        (
            self.gitVersion,
            self.boardVersion,
            self.dataVersion,
            self.mvPerADC,
            vc,
            self.bypassTempRaw,
            self.bypassVoltRaw,
            self.BCoeffInternal,
            self.BCoeffExternal,
            self.numSamples,
            self.loadResRaw,
        ) = self.S.unpack(data)

        self.voltageCalibration = FloatUint.U(vc)
        return self

    def to_cell(self, cell):
        cell.code_version = self.gitVersion
        cell.board_version = self.boardVersion
        cell.v_per_ADC = self.mvPerADC / 1000 / 64
        cell.v_calibration = self.voltageCalibration.f
        cell.load_maxtemp_raw = self.bypassTempRaw
        cell.balance_config_threshold_raw = self.bypassVoltRaw
        cell.internal_B = self.BCoeffInternal
        cell.external_B = self.BCoeffExternal
        cell.n_samples = self.numSamples
        cell.load_resistance_raw = self.loadResRaw / 16

    def __setstate__(self, m):
        self.gitVersion = m.get("gitV", None)
        self.boardVersion = m.get("hwV", None)
        self.dataVersion = m.get("dataV", None)
        self.mvPerADC = m.get("mvStep", None)
        self.voltageCalibration = m.get("vCal", None)
        self.bypassTempRaw = m.get("byTR", None)
        self.bypassVoltRaw = m.get("byVR", None)
        self.BCoeffInternal = m.get("bci", None)
        self.BCoeffExternal = m.get("bce", None)
        self.numSamples = m.get("nS", None)
        self.loadResRaw = m.get("lR", None)

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

@_dc("t<")
class RequestTiming:
    timer: int = None

    S: ClassVar = Struct("<H")
    T: ClassVar = PacketType.Timing

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        (self.timer,) = self.S.unpack(data)
        return self

    def to_bytes(self):
        return self.S.pack(self.timer & 0xFFFF)

    def __setstate__(self,m):
        self.timer = m.get("t", None)

    def __getstate__(self):
        return dict(t=self.timer)

@_dc("t>")
class ReplyTiming(RequestTiming):
    pass


@_dc("bcc<")
class ReplyBalanceCurrentCounter(_Reply):
    counter: int = None

    S: ClassVar = Struct("<I")
    T: ClassVar = PacketType.ReadBalanceCurrentCounter

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        (self.counter,) = self.S.unpack(data)
        return self

    def to_cell(self, cell):
        chg = False
        if cell.balance_current_count != self.counter:
            chg = True
            cell.balance_current_count = self.counter
        return chg

    def __setstate__(self, m):
        self.cmounter = m["c"]

    def __getstate__(self):
        return dict(c=self.counter)

@_dc("pid<")
class ReplyReadPIDconfig(_Reply):
    kp: int = None
    ki: int = None
    kd: int = None

    S: ClassVar = Struct("<III")
    T: ClassVar = PacketType.ReadPIDconfig

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        self.kp, self.ki, self.kd = self.S.unpack(data)
        return self

    def to_cell(self, cell):
        chg = False
        if (cell.pid_kp, cell.pid_ki, cell.pid_kd) != (self.kp, self.ki, self.kd):
            chg = True
            cell.pid_kp = self.kp
            cell.pid_ki = self.ki
            cell.pid_kd = self.kd
        return chg

    def __setstate__(self, m):
        self.kp = m["p"]
        self.ki = m["i"]
        self.kd = m["d"]

    def __getstate__(self):
        return dict(p=self.kp, i=self.ki, d=self.kd)


@_dc("bal>")
class RequestBalanceLevel:
    levelRaw: int = None

    S: ClassVar = Struct("<H")
    T: ClassVar = PacketType.WriteBalanceLevel

    @classmethod
    def from_cell(cls, cell):
        self = cls()
        self.levelRaw = cell.balance_threshold_raw
        return self

    def to_bytes(self):
        return self.S.pack(self.levelRaw or 0)

    def __setstate__(self, m):
        self.levelRaw = m["lR"]

    def __getstate__(self):
        return dict(lR=self.levelRaw)


@_dc("bal<")
class ReplyBalancePower(_Reply):
    pwm: int = None

    S: ClassVar = Struct("B")
    T: ClassVar = PacketType.ReadBalancePowerPWM

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        (self.pwm,) = self.S.unpack(data)
        return self

    def to_cell(self, cell):
        chg = False
        pwm = self.pwm / 255
        if cell.balance_pwm != pwm:
            chg = True
            cell.balance_pwm = pwm
        return chg

    def __setstate__(self, m):
        self.pwm = m["r"]

    def __getstate__(self):
        return dict(r=self.pwm)


@_dc("set>")
class RequestGetSettings(_Request):
    T = PacketType.ReadSettings


@_dc("ct>")
class RequestCellTemperature(_Request):
    T = PacketType.ReadTemperature


@_dc("bcc>")
class RequestBalanceCurrentCounter(_Request):
    T = PacketType.ReadBalanceCurrentCounter


@_dc("pc>")
class RequestPacketCounters(_Request):
    T = PacketType.ReadPacketCounters


@_dc("bp>")
class RequestBalancePower(_Request):
    T = PacketType.ReadBalancePowerPWM


@_dc("rpc>")
class RequestResetPacketCounters(_Request):
    T = PacketType.ResetPacketCounters


@_dc("rpcc>")
class RequestResetBalanceCurrentCounter(_Request):
    T = PacketType.ResetBalanceCurrentCounter


@_dc("cv>")
class RequestCellVoltage(_Request):
    T = PacketType.ReadVoltageAndStatus


@_dc("id>")
class RequestIdentifyModule(_Request):
    T = PacketType.Identify


@_dc("rpid>")
class RequestReadPIDconfig(_Request):
    T = PacketType.ReadPIDconfig


@_dc("cfg<")
class ReplyConfig(_Reply):
    T = PacketType.WriteSettings


@_dc("rbcc<")
class ReplyResetBalanceCurrentCounter(_Reply):
    T = PacketType.ResetBalanceCurrentCounter


@_dc("rpc<")
class ReplyResetPacketCounters(_Reply):
    T = PacketType.ResetPacketCounters


@_dc("bl<")
class ReplyBalanceLevel(_Reply):
    T = PacketType.WriteBalanceLevel


@_dc("id<")
class ReplyIdentify(_Reply):
    T = PacketType.Identify


@_dc("wpid<")
class ReplyWritePIDconfig(_Reply):
    T = PacketType.WritePIDconfig


requestClass = [
    RequestResetPacketCounters,  # ResetPacketCounters=0
    RequestCellVoltage,  # ReadVoltageAndStatus=1
    RequestIdentifyModule,  # Identify=2
    RequestCellTemperature,  # ReadTemperature=3
    RequestPacketCounters,  # ReadPacketCounters=4
    RequestGetSettings,  # ReadSettings=5
    RequestConfig,  # WriteSettings=6
    RequestBalancePower,  # ReadBalancePowerPWM=7
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
    ReplyResetPacketCounters,  # ResetPacketCounters=0
    ReplyVoltages,  # ReadVoltageAndStatus=1
    ReplyIdentify,  # Identify=2
    ReplyTemperature,  # ReadTemperature=3
    ReplyCounters,  # ReadPacketCounters=4
    ReplySettings,  # ReadSettings=5
    ReplyConfig,  # WriteSettings=6
    ReplyBalancePower,  # ReadBalancePowerPWM=7
    ReplyTiming,  # Timing=8
    ReplyBalanceCurrentCounter,  # ReadBalanceCurrentCounter=9
    ReplyResetBalanceCurrentCounter,  # ResetBalanceCurrentCounter=10
    ReplyBalanceLevel,  # WriteBalanceLevel=11
    ReplyWritePIDconfig,  # 12
    ReplyReadPIDconfig,  # 13
    NullData,  # 14
    NullData,  # 15
]

_k = None
for _k in globals().keys():
    if _k.startswith("Request") or _k.startswith("Reply"):
        __all__.append(_k)
del _k
