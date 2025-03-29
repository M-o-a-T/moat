"""
Basic client/server tests
"""

from __future__ import annotations

import pytest

from moat.modbus.client import ModbusClient
from moat.modbus.server import ModbusServer
from moat.modbus.types import FloatValue, HoldingRegisters, LongValue, StringValue


@pytest.mark.anyio()
async def test_rw():
    """Your basic client/server read/write test"""
    async with ModbusServer(address="127.0.0.1", port=0) as srv:
        sru = srv.add_unit(12)
        srv1 = sru.add(HoldingRegisters, 34, LongValue(123456))
        srv2 = sru.add(HoldingRegisters, 36, FloatValue(9999.125))
        srv3 = sru.add(HoldingRegisters, 38, StringValue(10, "hélþ"))

        async with (
            ModbusClient() as cli,
            cli.host("127.0.0.1", srv.port) as clh,
            clh.unit(12) as clu,
            clu.slot("x") as cls,
        ):
            clv1 = cls.add(HoldingRegisters, 34, LongValue())
            clv2 = cls.add(HoldingRegisters, 36, FloatValue())
            clv3 = cls.add(HoldingRegisters, 38, StringValue(10))

            await cls.getValues()  # pylint:disable=protected-access
            assert clv1.value == 123456
            assert clv2.value == 9999.125
            assert clv3.value == "hélþ"

            c = sru.store["h"].changed
            assert not c.is_set()
            clv1._value_w = 345678
            clv2._value_w = clv2._value * 3
            clv3._value_w = "CoMiNg"
            await cls.setValues()  # pylint:disable=protected-access
            assert srv1.value == 345678
            assert srv2.value == 9999.125 * 3
            assert srv3.value == "CoMiNg"
            assert c.is_set()
