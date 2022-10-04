
from ortools.linear_solver import pywraplp
from dataclasses import dataclass
 
class FutureData:
    """
    Collects projected data at some point in time.
    """
    price_buy: float = 0.0
    price_sell: float = 0.0
    load: float = 0.0
    pv: float = 0.0


def propose(battery, data, per_hour = 1):

    """
    Calculate optimum charge/discharge behavior based on
    minimizing cost / maximizing income.

    Input:
    * battery model + state
    * future data points
    * periods per hour

    """
    steps = len(data)
    energy = [None] * steps

    for i in range(steps):
        if data[i].pv >=50: energy[i] = data[i].load - data[i].pv
        else: energy[i] = data[i].load

    # battery
    capacity = battery.capacity
    charging_efficiency = battery.charging_efficiency
    discharging_efficiency = 1. / battery.discharging_efficiency
    current = capacity * battery.current_charge 
    limit = battery.charging_power_limit
    dis_limit = battery.discharging_power_limit

    limit /= per_hour
    dis_limit /= per_hour

    # ORtools
    solver = pywraplp.Solver("B", pywraplp.Solver.GLOP_LINEAR_PROGRAMMING)

    # Variables: all are continous
    charge = [solver.NumVar(0.0, limit, "c"+str(i)) for i in range(steps)] 
    dis_charge = [solver.NumVar( dis_limit, 0.0, "d"+str(i)) for i in range(steps)]
    battery_power = [solver.NumVar(capacity*0.05, capacity*.95, "b"+str(i)) for i in range(steps+1)]
    grid = [solver.NumVar(0.0, solver.infinity(), "g"+str(i)) for i in range(steps)] 

    #Objective function
    objective = solver.Objective()
    for i in range(steps):
        objective.SetCoefficient(grid[i], data[i].price_buy - data[i].price_sell)
        objective.SetCoefficient(charge[i], data[i].price_sell + data[i].price_buy / 1000.)
        objective.SetCoefficient(dis_charge[i], data[i].price_sell)             
    objective.SetMinimization()

    # 3 Constraints
    c_grid = [None] * steps
    c_power = [None] * (steps+1)

    # initial battery power
    c_power[0] = solver.Constraint(current, current)
    c_power[0].SetCoefficient(battery_power[0], 1)

    for i in range(0, steps):
        # grid - charge+discharge >= required energy
        c_grid[i] = solver.Constraint(energy[i], solver.infinity())
        c_grid[i].SetCoefficient(grid[i], 1)
        c_grid[i].SetCoefficient(charge[i], -1)
        c_grid[i].SetCoefficient(dis_charge[i], -1)
        # powerNext == powerNow + charge-discharge
        c_power[i+1] = solver.Constraint(0, 0)
        c_power[i+1].SetCoefficient(charge[i], charging_efficiency)
        c_power[i+1].SetCoefficient(dis_charge[i], discharging_efficiency)
        c_power[i+1].SetCoefficient(battery_power[i], 1)
        c_power[i+1].SetCoefficient(battery_power[i+1], -1)

    # solve the model
    solver.Solve()
    #return battery_power[1].solution_value() / capacity
    #print(objective.Value())

    if energy[0] < 0 and dis_charge[0].solution_value() >= 0:
        n = 0
        first = -limit
        mid = 0

        sum_charge = charge[0].solution_value()
        last = energy[0]
        for n in range(1, steps):
            if energy[n] > 0 or dis_charge[n].solution_value() < 0 or data[n].price_sell != data[n-1].price_sell:
                break
            last = min(last, energy[n])
            sum_charge += charge[n].solution_value()
        if sum_charge <= 0.05:
                return battery_power[1].solution_value() / capacity
        def tinh(X):
            res = 0
            for i in range(n):
                res += min(limit, max(-X - energy[i], 0.))
            return res >= sum_charge
        last = 2 - last
        # binary search
        while last - first > 1:
            mid = (first + last) / 2
            if tinh(mid): first = mid
            else: last = mid
        return (current + min(limit, max(-first - energy[0] , 0)) * charging_efficiency) / capacity
    
    if energy[0] > 0 and charge[0].solution_value() <= 0:
        n = 0
        first = dis_limit
        mid = 0
        sum_discharge = dis_charge[0].solution_value()
        last = energy[0]
        for n in range(1, steps):
            if energy[n] < 0 or charge[n].solution_value() > 0 or data[n].price_sell != data[n-1].price_sell or data[n].price_buy != data[n-1].price_buy:
                break
            last = max(last, energy[n])
            sum_discharge += dis_charge[n].solution_value()
        if sum_discharge >= 0.: 
            return battery_power[1].solution_value() / capacity

        def tinh2(X):
            res = 0
            for i in range(n):
                res += max(dis_limit, min(X - energy[i], 0))
            return res <= sum_discharge
        last += 2

        # binary search
        while last - first > 1:
            mid = (first + last) / 2
            if tinh2(mid): first = mid
            else: last = mid
        return (current + max(dis_limit, min(first - energy[0], 0)) * discharging_efficiency) / capacity

    return battery_power[1].solution_value() / capacity
