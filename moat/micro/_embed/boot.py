"MoaT satellite boot script"

# from moat import setup
# setup.run()
from __future__ import annotations

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
        print("No serial", exc)

print("\n*** MoaT ***\n", file=sys.stderr)
