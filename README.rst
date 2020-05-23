========
DistHASS
========

DistHASS is a link between Home Assistant and DistKV.

It will

* set up standard config for Home Assistant in DistKV

* have command-line support to register (or not) devices

Principle of Operation
======================

Home Assistant talks via MQTT. DistKV has a quite versatile MQTT adapter.
Thus we can store Home Assistant's entitiy configuration, plus their state,
plus the commands Home Assisant issues to get things to change their state,
in DistKV.

MQTT can only transmit binary data. DistHASS thus creates a few codecs that
support binary data (translating them to on/off), integers/floats, and JSON.

Thus, bottom to top:

* Mosquitto on port 51883

  * basic installation, does not need persistence or retained messages
  * Serf would work, but it imposes `additional delays <https://github.com/hashicorp/serf/issues/581>`_

* DistKV, using Mosquitto as a backbone

  * a special user with conversion rules for JSON etc.

* DistMQTT

  * retained messages are stored in DistKV
  * transparent channels to forward MQTT messages unmodified, if required
  * anything else is broadcast as a DistKV message
  * uses port 1883

* Home Assistant, or anything else MQTTish for that matter

  * must use MQTT 3.11

If you have devices that only can use MQTT 3.1, you can teach them to talk
directly to Mosquitto, via a transparent range.

Setup
=====

* Run ``distkv client hass init -i``

* Add a DistKV user for Home Assistant and set its ``conv`` parameter to ``hassco``::

    distkv client auth user param NAME conv hassco

* Start DistMQTT::

    distkv:
        server:
            host: '127.0.0.1'
            port: 27586
            auth: "password name=NAME password=PASSWORD"
        topic: [mqtt, msg]
        transparent:
        - [home,ass,event]
        - [home,ass,state]
        retain: [home, ass]
    listeners:
        default:
            max-connections: 500
            type: tcp
        local-tcp:
            bind: 127.0.0.1:1883
        remote-tcp:
            bind: 10.107.3.18:1883
    timeout-disconnect-delay: 2
    plugins: ['auth_anonymous']
    auth:
        allow-anonymous: true
    
  If you have devices that cannot talk via DistMQTT, modify the
  ``transparent`` list to include the MQTT prefixes you currently
  use.

* Modify Home Assistant's MQTT integration to do autodiscovery.
  If you've set it up via the GUI, the file you need is
  ``.storage/core.config_entries``. Find the entry with ``"domain":
  "mqtt"`` and modify its ``data`` entry to read::

                "data": {
                    "broker": "127.0.0.1",
                    "discovery": true,
                    "discovery_prefix": "home/ass/dyn",
                    "port": 1883,
                },

* Restart Home Assistant.

* Run ``distkv client hass add light foo bar``.

  A new light should show up in the Home Assistant GUI.
  
  You can try to turn it on, but it will go off by itself a second or two
  later because there's no device yet.

* Run ``distkv client hass state light foo bar True``.

  This command changes the state manually.

  In Home Assistant, the light turns on.

* Adding an actual device that monitors the light's DistKV command entry / its
  [Dist]MQTT command topic, actually affects the hardware, and changes the
  state, is your job.


