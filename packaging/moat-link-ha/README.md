# Home Assistant MQTT-discovery connector

% start synopsis
Manages Home-Assistant MQTT-discovery configuration stored in the MoaT-Link data tree.
% end synopsis

% start main

This module manages Home-Assistant device definitions.  It replaces the
legacy ``moat-kv-ha`` package.

## Quick start

1. Add a device (e.g. a light):

   ```shell
   moat link ha set light kitchen -s uid my-light-1
   ```

2. Show or list devices:

   ```shell
   moat link ha get light kitchen
   moat link ha get - -
   ```

## Deprecation

This package supersedes ``moat-kv-ha``.  Device configuration now lives
in MoaT-Link under the ``hass`` prefix.

% end main
