# Architecture — moat.mqtt (deprecated)

**Deprecated** MQTT 3.1.1 stack + broker. `__init__.py` says *"somewhat-mangled
clone of hbmqtt. Deprecated!"* New code uses `moat.lib.mqtt` — see
`moat-lib-mqtt/ARCHITECTURE.md`. Separate packages; neither wraps the other.

Still imported by: `moat.bus.server`, `moat.dev.sew`, `moat.kv.backend.mqtt`,
`moat.kv.mock.mqtt`.

## Client (`mqtt/client.py`)

A hand-rolled asyncio/anyio implementation — **not** a thin wrapper around an
external library.

- **`open_mqttclient(...)`** — async-context-manager constructing
  `MQTTClient(tg, client_id, config, codec)`.
- **`MQTTClient`** — owns a `Session`, a `PluginManager` (namespace
  `moat.mqtt.client.plugins`), and a `ClientProtocolHandler`
  (`mqtt/protocol/client_handler.py`). Speaks MQTT 3.1.1 directly via its own
  packet classes under `moat/mqtt/mqtt/` (`connect.py`, `publish.py`,
  `subscribe.py`, `connack.py`, …) and a custom codec layer (`codecs.py`).

## Transport (`mqtt/adapters.py`)

- **`StreamAdapter`** — raw TCP / TLS-wrapped (`anyio.connect_tcp` +
  `TLSStream.wrap`).
- **`WebSocketsAdapter`** — via `asyncwebsockets`.
- **`BufferAdapter`** — buffered.

Schemes `mqtt`, `mqtts`, `ws`, `wss` parsed from a URI.

## Features layered on raw MQTT

- Codec pluggability (`moat.lib.codec`, default `"noop"`).
- Per-topic QoS/retain config.
- Auto-reconnect with exponential backoff
  (`reconnect_max_interval`/`reconnect_retries`).
- `subscription()` async-iterator model backed by per-subscription queues
  dispatched by `_deliver_loop`/`_dispatch` with wildcard matching
  (`utils.match_topic`).
- `mqtt_connected` decorator gating calls behind `_connected_state`.

## Broker

`broker.py:create_broker` — a full broker with a plugin system (`plugins/`:
authentication, logging, persistence, topic-checking, manager). Plus a
MoaT-KV-backed broker (`moat_kv_broker.py`).

Essentially an entire MQTT 3.1.1 protocol stack reimplemented/forked from
hbmqtt, not a wrapper of paho-mqtt or aiomqtt.

## Relationship to moat.link

`moat.link` does **not** use this stack — it uses `moat.lib.mqtt`
(MQTT-5/vendored mqttproto) behind its backend. `moat.mqtt` survives only as a
dependency of the legacy subsystems listed above.
