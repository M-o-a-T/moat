from __future__ import annotations

from moat.lib.mqtt.sync_client import MQTTClient

with MQTTClient(path="/path/to/broker.sock", transport="unix") as client:
    ...
