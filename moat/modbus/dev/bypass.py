"""
Switchable bypass of a server unit: forward every request to a client unit.
"""

from __future__ import annotations

import anyio
import logging

from moat.util import NotGiven, to_attrdict
from moat.lib.modbus import ExcCodes, ExceptionResponse

from collections.abc import Mapping
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from anyio.abc import TaskStatus

    from moat.lib.modbus.pdu import PDU
    from moat.lib.path import Path
    from moat.link.client import LinkSender
    from moat.modbus.client import Unit

__all__ = ["Bypass"]

logger = logging.getLogger(__name__)


class Bypass:
    """
    Forwards a server unit's requests to a client unit while a flag is set.

    Args:
        link: The MoaT-Link client.
        cfg: The unit's ``bypass`` section. ``when`` is the flag's path, or
            ``[path, attr]``: the flag is the ``attr`` element of the value
            at ``path``. ``timeout`` (seconds, default 1.5) limits each
            forwarded request.
        target: The client unit to forward to.
        gate: A client unit whose own writes pause while the bypass is
            active.
    """

    active: bool = False
    """Whether requests are currently forwarded."""

    def __init__(
        self, link: LinkSender, cfg: Mapping[str, Any], target: Unit, gate: Unit | None = None
    ) -> None:
        when = cfg["when"]
        self.attr: Path | None
        if isinstance(when, (list, tuple)):
            self.path, self.attr = when
        else:
            self.path, self.attr = when, None
        self.timeout: float = cfg.get("timeout", 1.5)
        self.link = link
        self.target = target
        self.gate = gate

    def flag(self, value: Any) -> bool:
        """Extract the flag from the watched value."""
        if value is NotGiven or value is None:
            return False
        if self.attr is not None:
            if not isinstance(value, Mapping):
                return False
            value = to_attrdict(value).get_(self.attr, None)
        return value is True

    def set(self, active: bool) -> None:
        """Switch the bypass on or off."""
        if active == self.active:
            return
        logger.info("Bypass %s -> %s: %s", self.path, self.target, "on" if active else "off")
        self.active = active
        if self.gate is not None:
            self.gate.pause_writes(active)

    async def run(self, *, task_status: TaskStatus[None] = anyio.TASK_STATUS_IGNORED) -> None:
        """Watch the flag."""
        async with self.link.d_watch(self.path, mark=True) as mon:
            async for val in mon:
                if val is None:
                    task_status.started()
                    continue
                self.set(self.flag(val))

    async def forward(self, request: PDU) -> PDU:
        """Execute a request on the target unit and return its response."""
        try:
            with anyio.fail_after(self.timeout):
                return await self.target.process_request(request)
        except TimeoutError:
            return ExceptionResponse(request.function_code, ExcCodes.GATEWAY_TARGET_NO_RESPONSE)
