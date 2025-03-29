from __future__ import annotations
from moat.util import attrdict as ad, srepr
from moat.mqtt.client import open_mqttclient, QOS_1
from moat.modbus.types import HoldingRegisters as H, IntValue as I, SignedIntValue as S
from moat.modbus.client import ModbusClient
import anyio
import logging

logger = logging.getLogger(__name__)

__all__ = [
    "run",
]


class _Run:
    def __init__(self, cfg, name="moat.dev.sew"):
        self.cfg = cfg
        self.name = name

    async def _setup(self):
        "ensure that control registers control"
        cfg = self.cfg
        u = self.u

        async with u.slot("setup") as s:
            tmo = s.add(H, 505, S)  # P5-06 Timeout
            wr1 = s.add(H, 508, S)  # P5-09 Control input 2
            wr2 = s.add(H, 509, S)  # P5-10 Control input 3
            wr3 = s.add(H, 510, S)  # P5-11 Control input 4
            rd1 = s.add(H, 511, S)  # P5-12 Status output 2
            rd2 = s.add(H, 512, S)  # P5-13 Status output 3
            # rd3 = s.add(H,513,S)  # P5-14 Status output 4

            await s.getValues()

            def want(reg, val, txt):
                if reg.value != val:
                    logger.warning(
                        f"Change P{reg.offset // 100}-{(reg.offset % 100) + 1:02d} from {reg.value} to {val} ({txt})",
                    )
                    reg.set(val)

            want(tmo, int(cfg["timeout"] * 10 + 2.5), "timeout")
            want(wr1, 1, "speed percentage")
            want(wr2, 7, "unused")
            want(wr3, 7, "unused")
            want(rd1, 1, "speed percentage")
            want(rd2, 4, "power")
            # want(rd3,??)
            await s.setValues(changed=True)

    async def stop(self):
        self.ctrl.set(1)
        self.out_pct.set(0)
        await self.sc.setValues()

    async def _report(self, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Emit periodic status message
        """
        si = self.si
        timeout = self.cfg["timeout"] / 2
        info = self.info
        in_pct = self.in_pct
        in_power = self.in_power
        topic = "/".join(self.cfg["state"])
        REP = 10

        timeout /= 2
        t = anyio.current_time() + timeout
        prev_info = -1
        prev_pct = 0
        prev_power = 0
        rep = anyio.current_time()
        oreptxt = ""

        while True:
            await si.getValues()

            if (
                rep <= anyio.current_time()
                or info.value != prev_info
                or in_pct.value != prev_pct
                or in_power.value != prev_power
            ):
                rep = anyio.current_time() + REP
                v = info.value
                report = ad(
                    state=ad(
                        out=bool(v & 0x1),
                        ok=bool(v & 0x2),
                        error=bool(v & 0x20),
                    ),
                    power=in_power.value,
                    pct=in_pct.value / 0x4000,
                )
                vs = v >> 8
                if report.state.error:
                    report.state.err_state = vs
                elif (vs := v >> 8) == 1:
                    report.state.state = "STO"
                elif vs == 2:
                    report.state.state = "no_ok"
                elif vs == 5:
                    report.state.state = "c_speed"
                elif vs == 6:
                    report.state.state = "c_torque"
                elif vs == 0xA:
                    report.state.state = "tech"
                elif vs == 0xC:
                    report.state.state = "ref"
                else:
                    report.state.state = vs
                self.tg.start_soon(self.bus.publish, topic, report, QOS_1, False)

                report_txt = srepr(report)
                if report_txt != oreptxt:
                    print(report_txt)
                    oreptxt = report_txt

                prev_info = info.value
                prev_pct = in_pct.value
                prev_power = in_power.value

            task_status.started()
            task_status = anyio.TASK_STATUS_IGNORED

            t2 = anyio.current_time()
            if t2 < t:
                await anyio.sleep(t - t2)
                t += timeout
            else:
                logger.warning("DELAY %.3f", t2 - t)
                t = anyio.current_time() + timeout

    async def _control(self, task_status=anyio.TASK_STATUS_IGNORED):
        async with self.bus.subscription("/".join(self.cfg["power"])) as sub:
            task_status.started()
            async for msg in sub:
                if -1 <= msg.data <= 1:
                    await self.set_power(msg.data)
                else:
                    logger.error("?PWR %r", msg.data)

    async def set_power(self, pwr):
        if abs(pwr) < 0.001:
            logger.info("STOP")
            return await self.stop()

        logger.info("RUN %.3f", pwr)
        self.out_pct.set(int(0x4000 * pwr))
        self.ctrl.set(0x06)
        await self.sc.setValues(changed=True)

    async def run(self):
        cfg = self.cfg

        from moat.mqtt.client import open_mqttclient

        modbus = cfg["modbus"]
        async with (
            open_mqttclient(client_id=self.name, config=cfg["mqtt"]) as bus,
            ModbusClient() as g,
            g.conn(modbus) as c,
            c.unit(modbus["unit"]) as u,
            anyio.create_task_group() as tg,
            u.slot("ctrl") as sc,
            u.slot("stat") as si,
        ):
            self.u = u
            self.sc = sc
            self.si = si
            self.tg = tg
            self.bus = bus

            self.ctrl = sc.add(H, 0, I)
            self.out_pct = sc.add(H, 1, I)

            self.info = si.add(H, 5, I)
            self.in_pct = si.add(H, 6, I)
            self.in_power = si.add(H, 7, I)

            await self.stop()
            await self._setup()

            await tg.start(self._report)
            await tg.start(self._control)


async def run(*a, **kw):
    """Run a SEW MOVITRAC controller"""
    await _Run(*a, **kw).run()


async def set(cfg, val):
    async with open_mqttclient(config=cfg["mqtt"]) as bus:
        await bus.publish("/".join(cfg["power"]), val, QOS_1, False)
