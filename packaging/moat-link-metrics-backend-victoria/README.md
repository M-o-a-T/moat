# VictoriaMetrics backend for MoaT-Link metrics

% start synopsis
VictoriaMetrics time-series storage backend for moat-link-metrics.
% end synopsis

% start main

This package provides the VictoriaMetrics backend implementation for moat-link-metrics.
It allows forwarding metric values to a VictoriaMetrics time-series database.

## Installation

```shell
pip install moat-link-metrics-backend-victoria
```

Or for Debian-based systems:

```shell
apt install moat-link-metrics-backend-victoria
```

## Usage

The backend is automatically available once installed. To use it, set
`backend: victoria` in your server configuration.

## Configuration

The VictoriaMetrics backend supports the following configuration options in the
server config:

- **host**: VictoriaMetrics server hostname (default: `localhost`)
- **port**: VictoriaMetrics server port (default: `8282`)
- **delta**: Use delta compression (default: `true`)

## Example

```yaml
server:
  backend: victoria
  host: localhost
  port: 8282
  delta: true
```

% end main
