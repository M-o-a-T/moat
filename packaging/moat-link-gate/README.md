# moat-link-gate

% start synopsis
% start main

Gateway modules for MoaT-Link providing KV and MQTT integrations.

This package provides gateway functionality for MoaT-Link, including:
- MoaT-KV gateway for data storage integration
- Raw MQTT gateway, using configurable codecs
- Optional separate MQTT backend per gateway instance

% end synopsis

## Features

The gateway bidirectionally translates from MoaT-Link to various other
destinations. Messages are timestamped and marked, so there are no update
cycles.

## MQTT gateway

The MQTT gateway (driver ``mqtt``) bridges a subtree in MoaT-Link to a
subtree of MQTT topics.

### Configuration

The gate entry at ``:R.gate.NAME`` accepts:

``src``
  Source path inside MoaT-Link (``!P`` path).

``dst``
  Destination topic prefix on the MQTT broker (``!P`` path, must *not*
  be inside the MoaT-Link root).

``codec``
  Codec for external MQTT messages.  Either a codec name (string) or a
  ``!P`` path to a conversion vector stored under ``:R.conv``.

``backend`` *(optional)*
  When present, the gateway connects to a *separate* MQTT broker for its
  external side instead of reusing the primary MoaT-Link broker.  Any
  field supported by ``moat.link.backend.mqtt`` may be given here;
  ``driver`` defaults to ``mqtt``.  Example::

      backend:
        driver: mqtt
        host: broker.example.com
        port: 1883
        codec: std-cbor

  The backend connection is kept alive for the whole lifetime of the
  gateway and is torn down cleanly when the gateway stops.

``speed`` *(optional)*
  Minimum interval in seconds between consecutive writes to MoaT-Link
  for the same path.  Rapid external updates are coalesced.

% end main

## License

This project is licensed under the same terms as MoaT.
