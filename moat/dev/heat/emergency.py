"""
Emergency shutdown of the heat pump (HEAT.md §2.6).

The water pump must not stop while the heat exchanger still produces
heat, so shutting down is a sequence: take over the pump service (unless
the pump unit itself calls this), switch the heat pump off, drain the
heat through the flow unit, wait until the heat exchanger has cooled
down (or a timeout), then stop the water pump.
"""

from __future__ import annotations

import anyio
import logging
from contextlib import nullcontext

from moat.lib.path import P
from moat.util.time import time

from .config import EmergencyCfg, ServiceCfg, load_config
from .flow import FlowMode, FlowRequest
from .link import Reader

from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from moat.link.client import LinkSender

__all__ = ["PUMP_SERVICE", "emergency_shutdown"]

_logger = logging.getLogger(__name__)

PUMP_SERVICE = P("heat.pump")
"""The pump unit's service name, below ``run.host.<host>``."""

Result = Literal["cooled", "timeout", "total_timeout"]


async def _next_seq(link: LinkSender, path: Any) -> int:
    try:
        cur = await link.d_get(path)
    except KeyError:
        return 1
    seq = cur.get("seq") if isinstance(cur, dict) else None
    return (seq if isinstance(seq, int) else 0) + 1


async def _cool_down(link: LinkSender, cfg: EmergencyCfg) -> bool:
    "wait until fresh sensors show a cooled-down heat exchanger; False on timeout"
    r_in = Reader[float](link, cfg.sensor_in)
    r_out = Reader[float](link, cfg.sensor_out)

    def cooled() -> bool:
        now = time()
        if not (r_in.fresh(now, cfg.max_sensor_age) and r_out.fresh(now, cfg.max_sensor_age)):
            return False
        return r_out.value - r_in.value < cfg.stop_delta  # ty:ignore[unsupported-operator]

    async with anyio.create_task_group() as tg:
        await tg.start(r_in.run)
        await tg.start(r_out.run)
        try:
            with anyio.move_on_after(cfg.timeout):
                while not cooled():
                    # values change, and they also age
                    with anyio.move_on_after(1):
                        await r_out.wait_changed()
                return True
            return False
        finally:
            tg.cancel_scope.cancel()


async def emergency_shutdown(
    link: LinkSender,
    cfg: EmergencyCfg | None = None,
    *,
    from_pump: bool,
    service: ServiceCfg | None = None,
) -> Result:
    """
    Shut the heat pump down safely.

    Args:
        link: The MoaT-Link client.
        cfg: The procedure's tunables; default: ``cfg.app.heat.emergency``.
        from_pump: The pump unit calls this itself, so the pump service is
            not taken over.
        service: The shared service settings; default: ``cfg.app.heat.service``.

    Returns:
        How the cool-down ended: ``cooled``, ``timeout`` (the sensors never
        showed a cool heat exchanger), or ``total_timeout`` (the whole
        procedure took too long; the water pump may not have been told to
        stop).

    If another process owns the pump service (the pump unit), it is
    supplanted: its announcement monitor raises ``ServiceSupplanted``.
    The service is announced under the configured host name, not this
    machine's, so this works from any machine.
    """
    if cfg is None:
        cfg = await load_config(link, "emergency", EmergencyCfg)
    if service is None:
        service = await load_config(link, "service", ServiceCfg)

    result: Result = "total_timeout"
    with anyio.move_on_after(cfg.total_timeout):
        async with (
            nullcontext()
            if from_pump
            else link.announcing(PUMP_SERVICE, host=service.host, force=True)
        ) as srv:
            if srv is not None:
                srv.set()
            _logger.warning("Emergency shutdown of the heat pump")
            await link.d_set(cfg.power_path, 0, retain=True)
            await link.d_set(cfg.mode_path, cfg.mode_off, retain=True)
            seq = await _next_seq(link, cfg.flow_request)
            drain = FlowRequest(mode=FlowMode.DRAIN, rate=cfg.flow_rate, seq=seq)
            await link.d_set(cfg.flow_request, drain.to_link(), retain=True)

            cooled = await _cool_down(link, cfg)
            result = "cooled" if cooled else "timeout"
            if not cooled:
                _logger.warning("Emergency shutdown: no cool-down seen, stopping anyway")

            stop = FlowRequest(mode=FlowMode.OFF, seq=seq + 1)
            await link.d_set(cfg.flow_request, stop.to_link(), retain=True)
    if result == "total_timeout":
        _logger.error("Emergency shutdown did not finish in %s s", cfg.total_timeout)
    return result
