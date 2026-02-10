# Akumuli time-series connector

% start synopsis
Forwards MoaT-Link values to Akumuli time-series storage.
% end synopsis

% start main

This module watches MoaT-Link entries and writes their values to Akumuli
whenever they change.  It replaces the legacy ``moat-kv-akumuli`` package.

## Features

- Per-server configuration stored in MoaT-Link
- Dynamic series management: add, remove, or modify series at runtime
- Configurable scaling (factor/offset) and rate limiting (t_min)
- Attribute extraction from nested source values

## Quick start

1. Configure the Akumuli server:

   ```shell
   moat link akumuli add myserver my.entry source.path series_name host=myhost
   ```

2. Run the connector:

   ```shell
   moat link akumuli monitor myserver
   ```

## Deprecation of moat-kv-akumuli

This package supersedes ``moat-kv-akumuli``.  The raw MQTT topic monitoring
feature has been removed; use MoaT-Link's native data paths instead.

% end main
