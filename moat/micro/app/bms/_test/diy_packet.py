"""
Packet handler for diyBMS-serial mock battery
"""

from __future__ import annotations

import moat.ems.battery.diy_serial.packet as P
from moat.ems.battery.errors import MessageError
from moat.micro.conv.steinhart import celsius2thermistor

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.ems.battery.diy_serial.packet import _Reply

__all__ = [
    "MAXCELLS",
    "PacketHeader",
    "PacketType",
    "replyClass",
    "requestClass",
]

PacketType = P.PacketType
MAXCELLS = P.MAXCELLS


class PacketHeader(P.PacketHeader):
    def decode_one(self, msg):
        """Decode a single message to packet + rest.

        This method is used by the client.
        """
        off = 0
        RC = requestClass[self.command]
        pkt_len = RC.S.size
        pkt = None
        if pkt_len:
            if off + pkt_len > len(msg):
                raise MessageError(bytes(msg))  # incomplete
            pkt = RC.from_bytes(msg[off : off + pkt_len])
            if not self.broadcast:
                off += pkt_len
        if off:
            msg = memoryview(msg)[off:]
        return pkt, msg

    def encode_one(self, msg, pkt: _Reply = None):
        return self.to_bytes() + msg + (pkt.to_bytes() if pkt is not None else b"")


###


class ReplyIdentify(P.ReplyIdentify):
    def to_bytes(self):
        return b""


class RequestTiming(P.RequestTiming):
    async def to_cell(self, _cell):
        _cell._dp_t = self.timer  # noqa: SLF001


class ReplyTiming(P.ReplyTiming):
    async def from_cell(self, _cell):
        self.timer = _cell._dp_t  # noqa: SLF001


class ReplyReadSettings(P.ReplyReadSettings):
    async def from_cell(self, cell):
        bc_i, bc_e = await cell.b_coeff()
        s = await cell.settings()
        self.BCoeffInternal = bc_i
        self.BCoeffExternal = bc_e
        self.gitVersion = 0
        self.boardVersion = 0
        self.dataVersion = 0
        self.mvPerADC = int(s["vpa"] * 1000 * 64)
        self.voltageCalibration = s["vcal"]
        self.bypassTempRaw = 0
        self.bypassVoltRaw = 0
        self.numSamples = s["ns"]
        self.loadResRaw = int(4.2 * 16 + 0.5)

    def to_bytes(self):
        return self.S.pack(
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
        )


class ReplyVoltages(P.ReplyVoltages):
    def to_bytes(self):
        return self.S.pack(self.voltRaw, self.bypassRaw)

    async def from_cell(self, cell):
        u = await cell.u()
        bal = await cell.bal()

        self.voltRaw = await cell.v2raw(u)
        if bal.get("th", None) is None:
            self.bypassRaw = 0
        else:
            self.bypassRaw = await cell.v2raw(bal["th"])
        if bal["b"]:
            self.voltRaw |= 0x8000
        if bal["ot"]:
            self.voltRaw |= 0x4000


class ReplyTemperature(P.ReplyTemperature):
    async def from_cell(self, cell):
        t = await cell.t()
        tb = await cell.tb()
        bc_i, bc_e = await cell.b_coeff()
        self.intRaw = celsius2thermistor(bc_i, tb)
        self.extRaw = celsius2thermistor(bc_e, t)

    def to_bytes(self):
        b1 = self.intRaw & 0xFF
        b2 = (self.intRaw >> 8) | ((self.extRaw & 0x0F) << 4)
        b3 = self.extRaw >> 4
        return self.S.pack(b1, b2, b3)


requestClass = [
    P.RequestResetCounters,  # ResetCounters=0
    P.RequestVoltages,  # ReadVoltages=1
    P.RequestIdentify,  # Identify=2
    P.RequestTemperature,  # ReadTemperature=3
    P.RequestCounters,  # ReadCounters=4
    P.RequestReadSettings,  # ReadSettings=5
    P.RequestConfig,  # WriteSettings=6
    P.RequestBalancePower,  # ReadBalancePower=7
    RequestTiming,  # Timing=8
    P.RequestBalanceCurrentCounter,  # ReadBalanceCurrentCounter=9
    P.RequestResetBalanceCurrentCounter,  # ResetBalanceCurrentCounter=10
    P.RequestBalanceLevel,  # WriteBalanceLevel=11
    P.RequestWritePIDconfig,  # 12
    P.RequestReadPIDconfig,  # 13
]

replyClass = [
    P.ReplyResetCounters,  # ResetCounters=0
    ReplyVoltages,  # ReadVoltages=1
    P.ReplyIdentify,  # Identify=2
    ReplyTemperature,  # ReadTemperature=3
    P.ReplyCounters,  # ReadCounters=4
    ReplyReadSettings,  # ReadSettings=5
    P.ReplyConfig,  # WriteSettings=6
    P.ReplyBalancePower,  # ReadBalancePower=7
    ReplyTiming,  # Timing=8
    P.ReplyBalanceCurrentCounter,  # ReadBalanceCurrentCounter=9
    P.ReplyResetBalanceCurrentCounter,  # ResetBalanceCurrentCounter=10
    P.ReplyBalanceLevel,  # WriteBalanceLevel=11
    P.ReplyWritePIDconfig,  # 12
    P.ReplyReadPIDconfig,  # 13
]
