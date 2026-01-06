# moat-link-gate

% start synopsis
% start main

Gateway modules for MoaT-Link providing KV and MQTT integrations.

This package provides gateway functionality for MoaT-Link, including:
- MoaT-KV gateway for data storage integration
- "Raw" MQTT, using configurable codecs

% end synopsis

## Features

The gateway bidirectionally translates from MoaT-Link to various other
destinations. Messages are timestamped and marked, so there are no update
cycles.

% end main

## Usage

The gateways can be configured through MoaT-Link's configuration system.

## License

This project is licensed under the same terms as MoaT.
