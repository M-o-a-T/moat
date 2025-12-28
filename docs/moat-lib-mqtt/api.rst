API Reference
==============

Enumerated types
----------------

.. autoenum:: moat.lib.mqtt.PropertyType
.. autoenum:: moat.lib.mqtt.QoS
.. autoenum:: moat.lib.mqtt.ReasonCode
.. autoenum:: moat.lib.mqtt.RetainHandling
.. autoenum:: moat.lib.mqtt.MQTTClientState

Supporting classes
------------------

.. autoclass:: moat.lib.mqtt.Subscription
.. autoclass:: moat.lib.mqtt.Will

MQTT packet classes
-------------------

.. autoclass:: moat.lib.mqtt.MQTTPacket
.. autoclass:: moat.lib.mqtt.MQTTConnectPacket
.. autoclass:: moat.lib.mqtt.MQTTConnAckPacket
.. autoclass:: moat.lib.mqtt.MQTTPublishPacket
.. autoclass:: moat.lib.mqtt.MQTTPublishAckPacket
.. autoclass:: moat.lib.mqtt.MQTTPublishReceivePacket
.. autoclass:: moat.lib.mqtt.MQTTPublishReleasePacket
.. autoclass:: moat.lib.mqtt.MQTTPublishCompletePacket
.. autoclass:: moat.lib.mqtt.MQTTSubscribePacket
.. autoclass:: moat.lib.mqtt.MQTTSubscribeAckPacket
.. autoclass:: moat.lib.mqtt.MQTTUnsubscribePacket
.. autoclass:: moat.lib.mqtt.MQTTUnsubscribeAckPacket
.. autoclass:: moat.lib.mqtt.MQTTPingRequestPacket
.. autoclass:: moat.lib.mqtt.MQTTPingResponsePacket
.. autoclass:: moat.lib.mqtt.MQTTAuthPacket
.. autoclass:: moat.lib.mqtt.MQTTDisconnectPacket

Client-side state machine
-------------------------

.. autoclass:: moat.lib.mqtt.client_state_machine.MQTTClientStateMachine
   :inherited-members:

Broker-side state machines
--------------------------

.. autoclass:: moat.lib.mqtt.broker_state_machine.MQTTBrokerStateMachine
.. autoclass:: moat.lib.mqtt.broker_state_machine.MQTTBrokerClientStateMachine
   :inherited-members:

Concrete client implementations
-------------------------------

.. autoclass:: moat.lib.mqtt.async_client.AsyncMQTTClient
.. autoclass:: moat.lib.mqtt.async_client.AsyncMQTTSubscription
.. autoclass:: moat.lib.mqtt.sync_client.MQTTClient
.. autoclass:: moat.lib.mqtt.sync_client.MQTTSubscription

Concrete broker implementation
------------------------------

.. autoclass:: moat.lib.mqtt.async_broker.AsyncMQTTBroker
.. autoclass:: moat.lib.mqtt.async_broker.MQTTAuthenticator
.. autoclass:: moat.lib.mqtt.async_broker.MQTTAuthorizer
