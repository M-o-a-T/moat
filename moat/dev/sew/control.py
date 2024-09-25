from moat.mqtt.client import open_mqttclient, CodecError
from moat.modbus.types import HoldingRegisters as H, IntValue as I, SignedIntValue as S
from moat.modbus.client import ModbusClient
import anyio

__all__ = ["run", ]

async def _setup(cfg, u):
    "ensure that control registers control"
    async with u.slot("setup") as s:
        wr1 = s.add(H,508,S)  # P5-09
        wr2 = s.add(H,509,S)  # P5-10
        wr3 = s.add(H,510,S)  # P5-11
        rd1 = s.add(H,511,S)  # P5-12
        rd2 = s.add(H,512,S)  # P5-13
        #rd3 = s.add(H,513,S)  # P5-14

        await s._getValues()
        def want(reg,val,txt):
            if reg.value != want:
                breakpoint()
                logger.warn(f"Change P5-{reg.start+1 :%02d} from {reg.value} to {val} ({txt})")
                reg.set(val)

        want(wr1,1,"speed percentage")
        want(wr2,7,"unused")
        want(wr3,7,"unused")
        want(rd1,1,"speed percentage")
        want(rd2,4,"power")
        #want(rd3,??)
        await s._setValues(changed=True)


async def run(cfg, name="moat.dev.sew"):
    """Run a SEW MOVITRAC controller
    """
    from moat.mqtt.client import open_mqttclient, CodecError
    modbus = cfg["modbus"]
    async with (
        open_mqttclient(client_id=name, config=cfg["mqtt"], codec="msgpack") as bus,
        ModbusClient() as g,
        g.conn(modbus) as c,
        c.unit(modbus["unit"]) as u,
        anyio.create_task_group() as tg,
    ):
        await _setup(cfg, u)

