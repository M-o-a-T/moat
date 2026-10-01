# 1-Wire (OWFS) connector

% start synopsis
Connects MoaT-Link to 1-Wire buses via the asyncowfs library.
% end synopsis

% start main

This module bridges MoaT-Link values and 1-Wire device attributes, in
both directions, via the ``asyncowfs`` library.  It replaces the legacy
``moat-kv-ow`` package.

## Quick start

1. Configure an OWFS server (owserver):

   ```shell
   moat link ow server mybus add -h 10.0.0.1
   ```

2. Map a device attribute to a MoaT-Link path:

   ```shell
   moat link ow at 10.0bac6b010800.temperature add -s dest .data.temp.room -i 30
   ```

3. Run the connector (all servers):

   ```shell
   moat link ow monitor
   ```

## Deprecation

This package supersedes ``moat-kv-ow`` and uses the same data layout:
the configuration is keyed by device, not by bus, so devices can move
between buses (and owservers) and keep their settings.

% end main
