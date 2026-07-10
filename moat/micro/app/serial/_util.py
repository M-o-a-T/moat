"""
Utility functions for serial port apps.
"""

from __future__ import annotations

from moat.micro.part.serial import NamedSerial


def get_serial(cfg):
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
            __import__("moat.micro.part.serial", fromlist=("USBSerial",)),
            "USBSerial",
            None,
        )
        if Ser is None:
            Ser = NamedSerial
    else:
        Ser = NamedSerial
    return Ser(cfg)
