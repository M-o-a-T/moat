#struct PacketHeader
#{
#  uint8_t start;
#  unsigned int _reserved:2;
#  unsigned int global:1;
#  unsigned int seen:1;
#  unsigned int command:4;
#  uint8_t hops;
#  unsigned int cells:5;
#  unsigned int sequence:3;
#} __attribute__((packed));

from dataclasses import dataclass
from struct import Struct, pack, unpack
from typing import ClassVar
from enum import IntEnum

__all__ = [
        "PacketType", "PacketHeader", "requestClass", "replyClass",
        "MAXCELLS",
    ]
# more exports added at the end

MAXCELLS=32

try:
    _dc = dataclass(slots=True)
except TypeError:
    _dc = dataclass()

class PacketType(IntEnum):
    ResetPacketCounters=0
    ReadVoltageAndStatus=1
    Identify=2
    ReadTemperature=3
    ReadPacketCounters=4
    ReadSettings=5
    WriteSettings=6
    ReadBalancePowerPWM=7
    Timing=8
    ReadBalanceCurrentCounter=9
    ResetBalanceCurrentCounter=10
    WriteBalanceLevel=11


@_dc
class PacketHeader:
    start:int = 0
    broadcast:bool = False
    seen:bool = False
    command:int = 0
    hops:int = 0
    cells:int = 0
    sequence:int = 0

    S:ClassVar = Struct("BBBB")

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

    def to_bytes(self):
        return self.S.pack(
            self.start,
            (self.broadcast << 5) | (self.seen << 4) | (self.command & 0x0F),
            self.hops,
            (self.cells << 3) | (self.sequence & 0x07),
            )


class FloatUint:
    f = 0
    u = 0

    @classmethod
    def F(cls, val):
        self = cls()
        self.f = val
        self.u = unpack("<I",pack("f", val))

    @classmethod
    def U(cls, val):
        self = cls()
        self.u = val
        self.f = unpack("f",pack("<I", val))

class NullStruct:
    size = 0

class NullData:
    S:ClassVar = NullStruct


class _Request(NullData):
    @classmethod
    def from_cell(cls, cell):
        return cls()

    def to_bytes(self):
        return b''

class _Reply(NullData):
    @classmethod
    def from_bytes(cls, data):
        self = cls()
        if len(data):
            raise RuntimeError("I expect empty data")
        return self

    def to_cell(self, cell):
        pass

@_dc
class RequestConfig:
    voltageCalibration: FloatUint = FloatUint.U(0)
    bypassTempRaw: int = None
    bypassVoltRaw: int = None

    S:ClassVar = Struct("<IHH")
    T:ClassVar = PacketType.WriteSettings

    @classmethod
    def from_cell(self, cell):
        self.voltageCalibration = FloatUint.F(cell.v_calibration)
        self.bypassTempRaw = cell.bypass_temp_raw
        self.bypassVoltRaw = cell.balance_config_threshold_raw

    def to_bytes(self):
        vc = self.voltageCalibration.u
        return self.S.pack(vc, self.bypassTempRaw, self.bypassVoltRaw)

@_dc
class ReplyVoltages(_Reply):
    voltRaw: int = None
    bypassRaw: int = None

    S:ClassVar = Struct("<HH")
    T:ClassVar = PacketType.ReadVoltageAndStatus


    @classmethod
    def from_bytes(cls, data):
        self = cls()
        self.voltRaw, self.bypassRaw = self.S.unpack(data)

    def to_cell(self, cell):
        cell.in_bypass = bool(self.voltRaw & 0x8000)
        cell.bypass_over_temp = bool(self.voltRaw & 0x4000)
        vRaw = self.voltRaw & 0x1FFF
        if vRaw:
            cell.voltage = cell._raw2volt(vRaw)
            cell.valid = True
        return self

    def to_bytes(self):
        return self.S.pack(self.voltRaw, self.bypassRaw)

@_dc
class ReplyTemperature(_Reply):
    intRaw: int = None
    extRaw: int = None

    S:ClassVar = Struct("BBB")
    T:ClassVar = PacketType.ReadTemperature

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        b1,b2,b3 = self.S.unpack(data)
        self.intRaw = (b1 << 4) | (b2 >> 4);
        self.extRaw = ((b1 & 0x0F) << 8) | b2 >> 4;
        return self

    def to_cell(self, cell):
        cell.internal_temp_raw = self.intRaw
        cell.external_temp_raw = self.extRaw
    
@_dc
class ReplyCounters(_Reply):
    received: int = None
    bad: int = None

    S:ClassVar = Struct("<HH")
    T:ClassVar = PacketType.ReadPacketCounters

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        self.received, self.bad = self.S.unpack(data)
        return self

    def to_cell(self, cell):
        cell.packets_in = self.received
        cell.packets_bad = self.bad

@_dc
class ReplySettings(_Reply):
    gitVersion:int = None
    boardVersion:int = None
    dataVersion:int = None
    mvPerADC:int = None

    voltageCalibration:FloatUint = FloatUint.U(0)
    bypassTempRaw:int = None
    bypassVoltRaw:int = None
    BCoeffInternal:int = None
    BCoeffExternal:int = None
    numSamples:int = None
    loadResRaw:int = None

    S:ClassVar = Struct("<LHBBLHHHHBB")
    T:ClassVar = PacketType.ReadSettings

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
        cell.v_per_ADC = self.mvPerADC/1000
        cell.voltage_calibration = self.voltageCalibration.f
        cell.bypass_temp_raw = self.bypassTempRaw
        cell.balance_config_threshold_raw = self.bypassVoltRaw
        cell.internal_B = self.BCoeffInternal
        cell.external_B = self.BCoeffExternal
        cell.voltageSamples = self.numSamples
        cell.load_resistance = self.loadResRaw / 16

@_dc
class RequestTiming:
    timer: int = None

    S:ClassVar = Struct("<H")
    T:ClassVar = PacketType.Timing

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        self.timer, = self.S.unpack(data)
        return self

    def to_bytes(self):
        return self.S.pack(self.timer)

ReplyTiming = RequestTiming

@_dc
class ReplyBalanceCurrentCounter(_Reply):
    counter: int = None

    S:ClassVar = Struct("<I")
    T:ClassVar = PacketType.ReadBalanceCurrentCounter

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        self.counter, = self.S.unpack(data)
        return self

    def to_cell(self, cell):
        cell.balance_current_count = self.counter


@_dc
class RequestBalanceLevel:
    levelRaw: int = None

    S:ClassVar = Struct("<H")
    T:ClassVar = PacketType.WriteBalanceLevel

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        self.levelRaw, = self.S.unpack(data)
        return self

    def to_bytes(self):
        return self.S.pack(self.levelRaw)


@_dc
class ReplyBalancePower(_Reply):
    pwm: int = None

    S:ClassVar = Struct("B")
    T:ClassVar = PacketType.ReadBalancePowerPWM

    @classmethod
    def from_bytes(cls, data):
        self = cls()
        self.pwm, = self.S.unpack(data)
        return self

    def to_cell(self, cell):
        cell.bypass_pwm = self.pwm/255

class RequestGetSettings(_Request):
    T = PacketType.ReadSettings

class RequestCellTemperature(_Request):
    T = PacketType.ReadTemperature

class RequestBalanceCurrentCounter(_Request):
    T = PacketType.ReadBalanceCurrentCounter

class RequestPacketCounters(_Request):
    T = PacketType.ReadPacketCounters

class RequestBalancePower(_Request):
    T = PacketType.ReadBalancePowerPWM

class RequestResetPacketCounters(_Request):
    T = PacketType.ResetPacketCounters

class RequestResetBalanceCurrentCounter(_Request):
    T = PacketType.ResetBalanceCurrentCounter

class RequestCellVoltage(_Request):
    T = PacketType.ReadVoltageAndStatus

class RequestIdentifyModule(_Request):
    T = PacketType.Identify

class ReplyConfig(_Reply):
    T = PacketType.WriteSettings

class ReplyResetBalanceCurrentCounter(_Reply):
    T = PacketType.ResetBalanceCurrentCounter

class ReplyResetPacketCounters(_Reply):
    T = PacketType.ResetPacketCounters

class ReplyBalanceLevel(_Reply):
    T = PacketType.WriteBalanceLevel

class ReplyIdentify(_Reply):
    T = PacketType.Identify


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
    NullData,  # 12
    NullData,  # 13
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
    NullData,  # 12
    NullData,  # 13
    NullData,  # 14
    NullData,  # 15
]

_k = None
for _k in globals().keys():
    if _k.startswith("Request") or _k.startswith("Reply"):
        __all__.append(_k)
del _k
