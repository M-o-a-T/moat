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
        pass
    elif p == "USB":
        from moat.micro.part.serial import USBSerial  # noqa: PLC0415

        Ser = USBSerial
    else:
        Ser = NamedSerial
    return Ser(cfg)
