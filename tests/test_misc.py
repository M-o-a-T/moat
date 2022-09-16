"""
Basic client/server tests
"""
import pytest
import anyio

from moat.modbus.server import ModbusServer
from moat.modbus.client import ModbusClient
from moat.modbus.types import HoldingRegisters,LongValue,FloatValue

@pytest.mark.anyio
async def test_rw():
    async with ModbusServer(address="127.0.0.1", port=0) as srv:
        sru = srv.add_unit(12)
        srv1 = sru.add(HoldingRegisters,34,LongValue(123456))
        srv2 = sru.add(HoldingRegisters,36,FloatValue(9999.125))

        async with ModbusClient() as cli:
            clh = cli.host("127.0.0.1", srv.port)
            clu = clh.unit(12)
            cls = clu.slot("x")
            clv1 = cls.add(HoldingRegisters,34,LongValue)
            clv2 = cls.add(HoldingRegisters,36,FloatValue)

            await cls.getValues()
            assert clv1.value == 123456
            assert clv2.value == 9999.125
            clv2.value *= 3

            clv1.value = 345678
            await cls.setValues()
            assert srv1.value == 345678
            assert srv2.value == 9999.125*3




