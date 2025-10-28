"""
MoaT satellite boot script.

This file adds some essential setup.

Local code should go in "boot_local.py".
This file may be overwritten by a MoaT update.
"""

# from moat import setup
# setup.run()
from __future__ import annotations

import os
import sys

try:
    sys.path.remove("/lib")
except ValueError:
    pass
sys.path.insert(0, "/lib")

import moat  # just for the namespace

if not hasattr(moat, "SERIAL"):
    try:
        import usb.device
        from usb.device.cdc import CDCInterface

        moat.SERIAL = CDCInterface()
        try:
            moat.SERIAL.init(timeout=0)
            usb.device.get().init(moat.SERIAL, builtin_driver=True)
        except Exception:
            del moat.SERIAL
            raise
        finally:
            del CDCInterface
            del usb

    except Exception as exc:
        moat.SERIAL_EXC = exc

print("\n*** MoaT ***\n", file=sys.stderr)

# One line for handling boot_local, ten for not doing it. Fits.
try:
    from boot_local import *  # noqa:F403
except Exception as exc:  # noqa:F841  # SIGH
    for ext in ("py", "mpy"):
        try:
            os.stat(f"boot_local.{ext}")
        except OSError:
            pass
        else:
            exc = None
            break
    if exc is not None and (not isinstance(exc, ImportError) or "boot_local" not in repr(exc)):
        sys.print_exception(exc)
