from __future__ import annotations

from moat.lib.mqtt.sync_client import MQTTClient

with MQTTClient(host="localhost", ssl=True) as client:
    ...
