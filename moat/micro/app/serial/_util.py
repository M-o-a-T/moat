"""
Utility functions for serial port apps.
"""

from __future__ import annotations

from moat.micro.part.serial import NamedSerial

from typing import TYPE_CHECKING as _TC

if _TC:
    from typing import Any


def get_serial(cfg: dict) -> Any:
    """
    Get the appropriate serial class for the given config.

    Args:
        cfg: Configuration dict with 'port' key.

    Returns:
        A serial port instance.
    """
    p = cfg["port"]
    if not isinstance(p, str):
        Ser = p
    elif p == "USB":
        Ser = getattr(
            __import__("moat.micro.part.serial", globals(), None, ("USBSerial",)),
            "USBSerial",
            None,
        )
        if Ser is None:
            Ser = NamedSerial
    else:
        Ser = NamedSerial
    return Ser(cfg)
