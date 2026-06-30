# Architecture — moat.lib.mqtt

The **actively-used** MQTT client/broker stack. A continuation of
**mqttproto**, vendorized into MoaT. This is what `moat.link` uses; contrast
with the deprecated `moat.mqtt` (hbmqtt fork) — see `moat-mqtt/
ARCHITECTURE.md`.

## Files

- `__init__.py` — public API; states it is *"A continuation of mqttproto,
  vendorized into MoaT."*
- `async_client.py` — `AsyncMQTTClient` (attrs-defined, state-machine driven).
- `client_state_machine.py` / `broker_state_machine.py` — explicit state
  machines.
- `async_broker.py`, `sync_client.py` — broker and sync client.
- `_types.py` — MQTT-5 types: `PropertyType`, `RetainHandling`, `Will`,
  `ReasonCode`, `QoS`, `Subscription`, `Pattern`, full packet types.

## AsyncMQTTClient (`async_client.py`)

Attrs-defined client driven by `client_state_machine.MQTTClientStateMachine`.
Features:

- **MQTT-5** oriented (user properties, reason codes, retain handling).
- **`stamina` retries** for resilient connect/publish/subscribe.
- **Native WebSocket** support via `httpx_ws.AsyncWebSocketSession` wrapped
  as `MQTTWebsocketStream`.
- **Unix-socket** connect support.
- Typed exception hierarchy: `MQTTConnectFailed`, `MQTTPublishFailed`,
  `MQTTSubscribeFailed`, …

## How moat.link uses it

`moat/link/backend/mqtt.py:Backend` is the link-layer transport backend.
`connect()` opens `AsyncMQTTClient(*self.a, **self.kw)` from `cfg`
(host, codec, client_id, optional `Will`). Two codecs are kept: `self.codec`
(user-configured, e.g. `std-cbor`) for payloads and `self.mcodec`
(`get_codec("std-cbor")`) for metadata.

- **Send**: `Path` topic → `topic.slashed2()`, encode payload with `codec`
  (strings validated for MQTT-5 UTF-8 via `_is_valid_mqtt_utf8`; `NotGiven`
  ⇒ empty payload for deletion), attach `MsgMeta` as a `"MoaT"` user property,
  `client.publish(...)`. `retain` maps to link data lifecycle.
- **Monitor**: `Path` (+ optional `subtree` ⇒ append `/#`) →
  `client.subscribe(tops, no_local=not mine, retain_handling=…)`, returning a
  `_SubGet` async iterator that parses the MQTT topic back to a `Path`,
  extracts/decodes the `"MoaT"` user property into `MsgMeta`, and honors
  `PAYLOAD_FORMAT_INDICATOR` (0 ⇒ codec-decoded bytes; 1 ⇒ UTF-8 passthrough).
  Failures are reported to `:R.error.link.mqtt.{topic,meta,codec}`.

So MoaT-Link treats MQTT as one pluggable backend, translating `Path`-based
messages to flat MQTT topics and carrying structured metadata in MQTT-5 user
properties.

## Relationship to moat.mqtt

Separate packages. `moat.mqtt` (hbmqtt fork, MQTT 3.1.1) is legacy and still
imported by `moat.bus.server`, `moat.dev.sew`, `moat.kv.backend.mqtt`,
`moat.kv.mock.mqtt`. Neither wraps the other. New code uses `moat.lib.mqtt`.
