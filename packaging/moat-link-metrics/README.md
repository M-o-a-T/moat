# Metrics time-series connector

% start synopsis
Forwards MoaT-Link values to metrics time-series storage backends.
% end synopsis

% start main

This module watches MoaT-Link entries and writes their values to metrics backends
whenever they change. It replaces the legacy ``moat-kv-akumuli`` and ``moat-link-akumuli`` packages.

## Features

- Pluggable backend support (currently: Akumuli)
- Per-server configuration stored in MoaT-Link
- Dynamic series management: add, remove, or modify series at runtime
- Configurable scaling (factor/offset) and rate limiting (t_min)
- Attribute extraction from nested source values

## Quick start

1. Configure a metrics server:

   ```shell
   moat link metrics add myserver my.entry source.path series_name host=myhost
   ```

2. Run the connector:

   ```shell
   moat link metrics monitor myserver
   ```

## Backends

The default backend is Akumuli. To specify a different backend, set the `backend`
field in the server configuration to the backend module name (e.g., `akumuli`).

## Deprecation

This package supersedes ``moat-kv-akumuli`` and ``moat-link-akumuli``.  The raw
MQTT topic monitoring feature has been removed; use MoaT-Link's native data paths instead.

% end main
