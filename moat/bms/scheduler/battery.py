from dataclasses import dataclass

@dataclass
class Battery(object):
    """Stores information about the battery.

    current_charge: initial state of charge of the battery (0…1)
    capacity: useable battery capacity in Wh
    charging_power_limit: max charge power in W
    discharging_power_limit: max discharge power in W
    battery_charging_efficiency: Charging efficiency
    battery_discharing_efficiecny: Discharging efficiency
    """
    current_charge: float = 0.0
    capacity: float = 0.0
    charging_power_limit: float = 1.0
    discharging_power_limit: float = -1.0
    charging_efficiency: float = 0.95
    discharging_efficiency: float = 0.95

