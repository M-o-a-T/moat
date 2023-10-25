"""
Apps used for interconnecting.
"""

from __future__ import annotations

from moat.micro.alert import AlertHandler

# Typing
from typing import TYPE_CHECKING  # isort:skip

if TYPE_CHECKING:
    pass


class Alert(AlertHandler):
    """
    A rather basic test command.
    """

    pass
