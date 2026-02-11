# Akumuli backend for MoaT-Link metrics

% start synopsis
Akumuli time-series storage backend for moat-link-metrics.
% end synopsis

% start main

This package provides the Akumuli backend implementation for moat-link-metrics.
It allows forwarding metric values to an Akumuli time-series database.

## Installation

```shell
pip install moat-link-metrics-backend-akumuli
```

Or for Debian-based systems:

```shell
apt install moat-link-metrics-backend-akumuli
```

## Usage

The backend is automatically available once installed. To use it, set
`backend: akumuli` in your server configuration (this is the default).

## Configuration

The Akumuli backend supports the following configuration options in the
server config:

- **host**: Akumuli server hostname (default: `localhost`)
- **port**: Akumuli server port (default: `8282`)
- **delta**: Use delta compression (default: `true`)

## Example

```yaml
server:
  backend: akumuli
  host: localhost
  port: 8282
  delta: true
```

% end main
