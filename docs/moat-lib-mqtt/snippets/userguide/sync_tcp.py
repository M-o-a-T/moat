from __future__ import annotations

from moat.lib.mqtt.sync_client import MQTTClient

with MQTTClient(host_or_path="localhost") as client:
    ...
