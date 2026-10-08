from __future__ import annotations

from moat.lib.mqtt.sync_client import MQTTClient

with MQTTClient(host="localhost", websocket_path="/ws", ssl=True) as client:
    ...
