"""
Code to set up a link to a MicroPython client device
"""
from __future__ import annotations

import hashlib
import io
import logging
from itertools import chain
from pathlib import Path

from moat.util import NotGiven, attrdict

from moat.micro.cmd.base import BaseCmd
from moat.micro.compat import Event, TaskGroup
from moat.micro.stacks.console import console_stack

logger = logging.getLogger(__name__)


class ClientBaseCmd(BaseCmd):
    """
    a BaseCmd subclass that adds link state tracking
    """

    def __init__(self, cfg):
        super().__init__(cfg)
        self.started = Event()

    def cmd_link(self, s=None):  # pylint: disable=unused-argument
        """Link-up command handler, sets `started`"""
        self.started.set()

    async def wait_start(self):
        """Wait until a "link" command arrives"""
        await self.started.wait()

