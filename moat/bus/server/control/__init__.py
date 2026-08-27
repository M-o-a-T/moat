"""
Handler for control messages.

Just dispatch them.
"""

from __future__ import annotations

from moat.bus.util import SubDispatch

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.bus.message import BusMessage


# import logging
# logger = logging.getLogger(__name__)


class ControlHandler(SubDispatch):
    """
    Read and process control messages from the server.

    Usage::
        async with ControlHandler(server) as CH:
            async with CH.with_code(2) as CM:
                await process_console_messages(CM)
    """

    CODE = 0

    def get_code(self, msg: BusMessage) -> int | None:
        """Get dispatch code for this message."""
        if len(msg.data) == 0:
            return None
        return msg.data[0] >> 5
