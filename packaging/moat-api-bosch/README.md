# MoaT API: Bosch Sensortec

% start synopsis
% start main

This module collects CFFI-based Python wrappers for Bosch Sensortec sensors.

- BMV080 Particulate Matter Sensor

% end synopsis

## Requirements

- BMV080: the shared libraries (`libbmv080.so` / `bmv080.dll`) must be
  obtained from Bosch Sensortec.

## Availability

The Bosch libraries may or may not be available for your OS and architecture.
If they are not, acquire a suitable device (e.g. a Raspberry Pi 4) and use
MoaT-Link to connect to the library remotely.

% end main

## License

This library is licensed under the MIT license. The license of the Bosch
binares unfortunately does not explicitly allow redistribution, thus they
cannot be included here.
