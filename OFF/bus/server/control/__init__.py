"""
Handler for control messages.

Just dispatch them.
"""

from ...util import SubDispatcher

# import logging
# logger = logging.getLogger(__name__)


class ControlHandler(SubDispatcher):
    """
    Read and process control messages from the server.

    Usage::
        async with ControlHandler(server) as CH:
            async with CH.with_code(2) as CM:
                await process_console_messages(CM)
    """

    CODE = 0

    def get_code(self, msg):
        """Get dispatch code for this message"""
        if len(msg.data) == 0:
            return None
        return msg.data[0] >> 5
