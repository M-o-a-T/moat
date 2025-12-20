#!/usr/bin/python3

from moat.lib.pid import PID
from examples.mass_spring_damper import MassSpringDamper
from matplotlib import pyplot as plt
from numpy import diff

# Create a mass-spring-damper system model
system = MassSpringDamper(mass=1.0, spring_const=1.0, damping_const=0.2)
system.set_initial_value(initial_position=1.0, initial_velocity=0.0)

# Create PID controller
pid = PID(Kp=1.0, Ki=0.0, Kd=2.0, Tf=0.5)

# Control loop
time, meas, cont = [], [], []
for i in range(800):
    # Get current measurement from system
    timestamp, measurement = system.get_measurement()

    # Calculate control signal by using PID controller
    control = pid(-measurement, t=timestamp)

    # Feed control signal to system
    system.set_input(control)

    # Record for plotting
    time.append(timestamp)
    meas.append(measurement)
    cont.append(control)

# Plot result
fig, (ax1, ax2, ax3) = plt.subplots(3, 1)
fig.suptitle('Mass-Spring-Damper system')
ax1.set_ylabel('Measured Position [m]')
ax1.plot(time, meas, 'b')
ax1.grid()
ax2.set_ylabel('Force [N]')
ax2.plot(time, cont, 'g')
ax2.grid()
ax3.set_xlabel('Time [s]')
ax3.set_ylabel('Derivative Term')
ax3.plot(time[1:], diff(meas)/diff(time), 'r')
ax3.grid()
plt.show()
