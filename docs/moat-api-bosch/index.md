# MoaT API: Bosch Sensortec

```{include} ../../packaging/moat-api-bosch/README.md
:start-after: % start synopsis
:end-before: % start synopsis
```

## API Reference

```{eval-rst}
.. automodule:: moat.api.bosch.bmv080
   :members:
   :undoc-members:
   :show-inheritance:
```
### Usage

```python
from moat.api.bosch.bmv080 import BMV080, BMV080Output

class MySPILink:
    """Example SPI link implementation."""

    def read(self, header: int, length: int) -> list[int]:
        # Implement SPI read
        ...

    def write(self, header: int, payload: list[int]) -> None:
        # Implement SPI write
        ...

    def delay_ms(self, duration_ms: int) -> None:
        # Implement delay
        import time
        time.sleep(duration_ms / 1000)

    def time_ms(self) -> int:
        # Return monotonic tick in milliseconds
        import time
        return int(time.monotonic() * 1000)

# Create link and sensor
spi = MySPILink()

with BMV080(spi, "/path/to/libbmv080.so") as sensor:
    # Get sensor info
    print(f"Driver version: {sensor.get_driver_version()}")
    print(f"Sensor ID: {sensor.get_sensor_id()}")

    # Configure (optional)
    sensor.set_parameter("integration_time", 10.0)
    sensor.set_parameter("do_vibration_filtering", True)

    # Start measurement
    sensor.start_continuous_measurement()

    try:
        while True:
            for output in sensor.serve_interrupt():
                print(f"PM2.5: {output.pm2_5_mass_concentration:.1f} µg/m³")
            time.sleep(1)
    finally:
        sensor.stop_measurement()
```

### Custom Processing

Override the `process` method to handle measurements:

```python
class MyBMV080(BMV080):
    def process(self, output: BMV080Output) -> None:
        if output.is_obstructed:
            print("Warning: sensor obstructed!")
        if output.pm2_5_mass_concentration > 25:
            print("Air quality alert!")
```

### Parameters

Available parameters for `set_parameter()`:

| Key | Type | Unit | Default | Description |
|-----|------|------|---------|-------------|
| `integration_time` | float | s | 10 | Measurement window |
| `duty_cycling_period` | int | s | 30 | Duty cycling period |
| `do_obstruction_detection` | bool | | true | Enable obstruction detection |
| `do_vibration_filtering` | bool | | false | Enable vibration filter |
| `measurement_algorithm` | int | | 3 | 1=fast, 2=balanced, 3=high precision |

### Requirements

- The BMV080 shared library (`libbmv080.so` / `bmv080.dll`) must be
  obtained separately from Bosch Sensortec.
- Library version must be >= 11.2.0 and < 12.0.0.
- The caller must provide a link object implementing `BMV080_Link` with
  `read`, `write`, `delay_ms`, and `time_ms` methods.
