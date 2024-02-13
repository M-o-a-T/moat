
"""
Test implementation of something that may or may not behave like a battery
"""

from __future__ import annotations

import random
import sys

def Comm(cfg):
    from moat.ems.battery.diy_serial.comm import BattComm
    return BattComm(cfg)

