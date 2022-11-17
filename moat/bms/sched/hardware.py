# pylint: disable=missing-module-docstring

from dataclasses import dataclass


@dataclass
class Hardware:
    """Stores information about the hardware used.

    capacity: useable battery capacity in kWh
    batt_max_soc: max battery SoC, default 0.95
    batt_min_soc: min battery SoC, default 0.25
    batt_max_chg: max battery charge power in kW
    batt_max_dis: max battery discharge power in kW
    batt_eff_chg: charger efficienty (0…1)
    batt_eff_dis: discharger efficiency (0…1)
    inv_max_chg: max charger power (AC to DC) in kW
    inv_max_dis: max inverter power (DC to AC) in kW
    inv_eff_chg: charger efficienty (0…1)
    inv_eff_dis: inverter efficiency (0…1)
    grid_max_in: max grid input
    grid_max_out: max grid output
    """

    capacity: float = 0.0
    batt_max_soc: float = 0.95
    batt_min_soc: float = 0.25
    batt_max_chg: float = 1
    batt_max_dis: float = 1
    batt_eff_chg: float = 0.98
    batt_eff_dis: float = 0.98
    inv_max_chg: float = 2.5
    inv_max_dis: float = 2.5
    inv_eff_chg: float = 0.9
    inv_eff_dis: float = 0.9
    grid_max_in: float = 63
    grid_max_out: float = 63
