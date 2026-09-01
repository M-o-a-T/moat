# GPIO controller connector

% start synopsis
Connects MoaT-Link to GPIO lines via the moat-lib-gpio library.
% end synopsis

% start main

This module bridges MoaT-Link values and GPIO controller lines, in both
directions.  It replaces the legacy ``moat-kv-gpio`` package.

## Quick start

1. Configure an input line (reads GPIO and publishes to a link path):

   ```shell
   moat link gpio port myhost 0 5 -t input -m read -a dest .sensors.button
   ```

2. Configure an output line (watches a link path and drives GPIO):

   ```shell
   moat link gpio port myhost 0 3 -t output -m write -a src .controls.lamp
   ```

3. Run the connector for a chip:

   ```shell
   moat link gpio monitor myhost 0
   ```

## Deprecation

This package supersedes ``moat-kv-gpio``.  The address tree now lives in
MoaT-Link under the ``gpio`` prefix; lines are stored as integer line
numbers below host and chip entries.

% end main
