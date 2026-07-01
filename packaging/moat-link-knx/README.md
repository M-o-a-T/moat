# KNX bus connector

% start synopsis
Connects MoaT-Link to a KNX bus via XKNX/KNXnet/IP tunneling.
% end synopsis

% start main

This module bridges MoaT-Link values and KNX group addresses, in both
directions, via the XKNX library.  It replaces the legacy
``moat-kv-knx`` package.

## Quick start

1. Configure a KNX gateway:

   ```shell
   moat link knx myhouse add -h 10.0.0.1
   ```

2. Map a group address to a MoaT-Link path:

   ```shell
   moat link knx myhouse at 1/2/3 add -t in -m Bool -s dest .data.lamp.kitchen
   ```

3. Run the connector:

   ```shell
   moat link knx myhouse monitor
   ```

## Deprecation

This package supersedes ``moat-kv-knx``.  The address tree now lives in
MoaT-Link under the ``knx.<NAME>`` prefix; group addresses are stored as
the three integer components of an ``a/b/c`` address.

% end main
