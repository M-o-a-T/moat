# moat-lib-pid

% start main
% start synopsis

An advanced PID controller in Python. It does not require a fixed feed
rate, supports anti-windup, and contains an optional first-order filter for
the derivative term.

% end synopsis

This module was vendorized from the advanced-pid module by Erkan Adali <erkanadali91@gmail.com>.

MoaT improvements include

- a `CPID` subclass with a settable reference
- saving internal state, for crash recovery and rebooting
- introspection

## Usage

Usage is very simple:

```python
from moat.lib.pid import PID

# Create PID controller
pid = PID(Kp=2.0, Ki=0.1, Kd=1.0, Tf=0.05)

# Control loop

reference = 1.0

while True:
    # Get current measurement from system
    timestamp, measurement = system.get_measurement()

    # Calculate control signal by using PID controller
    control = pid(reference - measurement, t=timestamp)

    # Feed control signal to system
    system.set_input(control)
```

The package's examples includes a toy mass-spring-damper system model for testing.

% end main

## License

Licensed under the
[MIT License](https://github.com/eadali/advanced-pid/blob/main/LICENSE.md).
