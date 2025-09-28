"""
Communicate with diyBMS (MoaT firmware)
"""

from __future__ import annotations


def Comm(cfg):
    """
    Communicator for the serially-connected cell controllers.

    This app accepts control packets, encodes and forwards them
    to the link, and returns the reply packets.
    """
    from moat.ems.battery.diy_serial.comm import BattComm  # noqa: PLC0415

    return BattComm(cfg)


def Cell(cfg):
    """
    Direct interface to a single cell.

    @comm: BattComm instance
    @i: cell number there

    This BaseCell translates commands to Comm requests.
    """
    from moat.ems.battery.diy_serial.cell import Cell  # noqa: PLC0415

    return Cell(cfg)
