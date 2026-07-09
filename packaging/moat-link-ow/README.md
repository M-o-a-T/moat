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
   moat link ow mybus add -h 10.0.0.1
   ```

2. Map a device attribute to a MoaT-Link path:

   ```shell
   moat link ow mybus at 10.345678.90 temperature add -s dest .data.temp.room -s interval =5
   ```

3. Run the connector:

   ```shell
   moat link ow mybus monitor
   ```

## Deprecation

This package supersedes ``moat-kv-ow``.  The address tree now lives in
MoaT-Link under the ``ow.<NAME>`` prefix; device attributes are stored
below the server entry, keyed by family code, hardware code, and the
attribute path.

% end main
