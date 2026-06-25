# Wago controller connector

% start synopsis
Connects MoaT-Link to Wago bus controllers via the asyncwago library.
% end synopsis

% start main

This module bridges MoaT-Link values and Wago controller ports, in both
directions, via the ``asyncwago`` library.  It replaces the legacy
``moat-kv-wago`` package.

## Quick start

1. Configure a Wago controller:

   ```shell
   moat link wago myctrl add -h 10.0.0.1
   ```

2. Map a port to a MoaT-Link path:

   ```shell
   moat link wago myctrl at input 1 3 add -m read -s dest .data.lamp.kitchen
   ```

3. Run the connector:

   ```shell
   moat link wago myctrl monitor
   ```

## Deprecation

This package supersedes ``moat-kv-wago``.  The address tree now lives in
MoaT-Link under the ``wago.<NAME>`` prefix; ports are stored as
``input`` or ``output`` type, then card number, then port number.

% end main
