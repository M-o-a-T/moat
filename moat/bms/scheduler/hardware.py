from dataclasses import dataclass

@dataclass
class Hardware(object):
    """Stores information about the hardware used.

    capacity: useable battery capacity in Wh
    batt_max_chg: max battery charge power in W
    batt_max_dis: max battery discharge power in W
    batt_eff_chg: charger efficienty (0…1)
    batt_eff_dis: discharger efficiency (0…1)
    inv_max_chg: max charger power (AC to DC) in W
    inv_max_dis: max inverter power (DC to AC) in W
    inv_eff_chg: charger efficienty (0…1)
    inv_eff_dis: inverter efficiency (0…1)
    grid_max_in: max grid input
    grid_max_out: max grid output
    """
    capacity: float = 0.0
    batt_max_chg: float = 1
    batt_max_dis: float = 1
    batt_eff_chg: float = 0.95
    batt_eff_dis: float = 0.95
    inv_max_chg: float = 10000
    inv_max_dis: float = 10000
    inv_eff_chg: float = 0.9
    inv_eff_dis: float = 0.9
    grid_max_in: float = 99999
    grid_max_out: float = 99999

