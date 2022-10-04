
from ortools.linear_solver import pywraplp
from dataclasses import dataclass
 
@dataclass
class FutureData:
    """
    Collects projected data at some point in time.
    """
    price_buy: float = 0.0
    price_sell: float = 0.0
    load: float = 0.0
    pv: float = 0.0


class Model:
    """
    Calculate optimum charge/discharge behavior based on
    minimizing cost / maximizing income.

    Initial input:
    * hardware model
    * future data points
    * periods per hour

    Solver input:
    * current charge level (SoC)

    Output (first period):
    * grid input (negative: send energy)
    * battery SoC at end of first period

    No other output is provided. Re-run the model with the actual SoC at
    the start of the next period.
    """

    def __init__(self, hardware, data, per_hour = 1):
        self.hardware = hardware
        self.data = data
        self.per_hour = per_hour

        self.setup()

    def setup(self):
        hardware = self.hardware
        data = self.data
        per_hour = self.per_hour

        steps = len(data)

        # ORtools
        self.solver = solver = pywraplp.Solver("B", pywraplp.Solver.GLOP_LINEAR_PROGRAMMING)
        self.objective = solver.Objective()

        # Starting battery charge
        self.cap_init = cap_prev = solver.NumVar(hardware.capacity*0.05, hardware.capacity*.95, "b_init")
        self.constr_init = solver.Constraint(0, 0)
        self.constr_init.SetCoefficient(self.cap_init, 1)

        for i in range(steps):
            # input constraints
            dt = data[i]
            if dt.price_buy == dt.price_sell:
                dt.price_buy *= 1.001
            elif dt.price_buy < dt.price_sell:
                raise ValueError(f"At {i}: buy {dt.price_buy} < sell {dt.price_sell} ??")

            # ### Variables to consider

            # future battery charge
            cap = solver.NumVar(hardware.capacity*0.05, hardware.capacity*.95, f"b{i}")

            # battery charge/discharge
            b_chg = solver.NumVar(0, hardware.batt_max_chg / per_hour, f"bc{i}")
            b_dis = solver.NumVar(0, hardware.batt_max_dis / per_hour, f"bd{i}")

            # solar power input. We may not be able to take all
            s_in = solver.NumVar(0, dt.pv / per_hour, f"pv{i}")

            # inverter charge/discharge
            i_chg = solver.NumVar(0, hardware.inv_max_chg / per_hour, f"ic{i}")
            i_dis = solver.NumVar(0, hardware.inv_max_dis / per_hour, f"id{i}")

            # local load
            l_out = solver.NumVar(dt.load, dt.load / per_hour, f"ld{i}")

            # grid
            g_in = solver.NumVar(0, hardware.grid_max_in / per_hour, f"gi{i}")
            g_out = solver.NumVar(0, hardware.grid_max_out / per_hour, f"go{i}")

            # income to maximize
            money = solver.NumVar(-solver.infinity(), solver.infinity(), f"pr{i}")

            # ### Constraints (actually Relationships, as they're all equalities)

            # Battery. old + charge - discharge == new, so … - new == 0.
            _bt = solver.Constraint(0, 0)
            _bt.SetCoefficient(cap_prev, 1)
            _bt.SetCoefficient(b_chg, hardware.batt_eff_chg)
            _bt.SetCoefficient(b_dis, -1)
            _bt.SetCoefficient(cap, -1)

            # DC power bar. power_in - power_out == zero.
            _dc = solver.Constraint(0, 0)
            # Power in
            _dc.SetCoefficient(s_in, 1)
            _dc.SetCoefficient(b_dis, hardware.batt_eff_dis)
            _dc.SetCoefficient(i_chg, hardware.inv_eff_chg)
            # Power out
            _dc.SetCoefficient(b_chg, -1)
            _dc.SetCoefficient(i_dis, -1)

            # AC power bar. power_in - power_out == zero.
            _ac = solver.Constraint(0, 0)
            # Power in
            _ac.SetCoefficient(g_in, 1)
            _ac.SetCoefficient(i_dis, hardware.inv_eff_dis)
            # Power out
            _ac.SetCoefficient(g_out, -1)
            _ac.SetCoefficient(l_out, -1)
            _ac.SetCoefficient(i_chg, -1)

            # Money earned: grid_out*price_sell - grid_in*price_buy == money, so … - money = zero.
            _pr = solver.Constraint(0, 0)
            _pr.SetCoefficient(g_out, dt.price_sell)
            _pr.SetCoefficient(g_in, -dt.price_buy)
            _pr.SetCoefficient(money, -1)

            self.objective.SetCoefficient(money, 1)
            cap_prev = cap
            if not i:
                self.g_in,self.g_out = g_in,g_out
                self.cap = cap
                self.money = money

        self.objective.SetMaximization()

    def propose(self, charge):
        charge *= self.hardware.capacity
        self.constr_init.SetLb(charge)
        self.constr_init.SetUb(charge)

        self.solver.Solve()
        return self.g_in.solution_value() - self.g_out.solution_value(), self.cap.solution_value()/self.hardware.capacity, self.money.solution_value()/1000

