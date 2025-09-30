==========
MoaT-KV-HA
==========

This is a link between Home Assistant and Moat-KV.

It will

* set up standard config for Home Assistant in MoaT-KV

* have command-line support to register (or not) devices

Principle of Operation
======================

Home Assistant talks via MQTT. MoaT-KV has a quite versatile MQTT adapter.
Thus we can store Home Assistant's entitiy configuration, plus their state,
plus the commands Home Assisant issues to get things to change their state,
in MoaT-KV.

MQTT can only transmit binary data. DistHASS thus creates a few codecs that
support binary data (translating them to on/off), integers/floats, and JSON.

Thus, bottom to top:

* Mosquitto on port 51883

  * basic installation, does not need persistence or retained messages

* MoaT-KV, using Mosquitto as a backbone

  * a special user with conversion rules for JSON etc.

* DistMQTT

  * retained messages are stored in MoaT-KV
  * transparent channels to forward MQTT messages unmodified, if required
  * anything else is broadcast as a MoaT-KV message
  * uses port 1883

* Home Assistant, or anything else MQTTish for that matter

  * must use MQTT 3.11

If you have devices that only can use MQTT 3.1, you can teach them to talk
directly to Mosquitto, via a transparent range.

Setup
=====

* Run ``moat kv ha init -i``

* Add a MoaT-KV user for Home Assistant and set its ``conv`` parameter to ``hassco``::

    moat kv auth user param NAME conv hassco

* Start Moat-MQTT with something like this configuration::

    kv:
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

  If you have devices that use MQTT directly, modify the
  ``transparent`` list to include your current MQTT prefixes.

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

* Run ``moat kv ha conv``.

  This teaches MoaT-KV to auto-convert the Home Assistant data so that
  everything in MoaT-KV sees binary states as booleans, temperatures are
  floats, the configuration's JSON is a real data structure, and so on.

  Without this conversion, it's all strings. We don't want that.

* Restart Home Assistant.

* Run ``moat kv ha add light foo bar``.

  A new light should show up in the Home Assistant GUI.

  You can try to turn it on, but it will go off by itself a second or two
  later because there's no device yet.

* Run ``moat kv ha state light foo bar True``.

  This command changes the state manually.

  In Home Assistant, the light's indicator turns on.

* Adding an actual device that monitors the light's MoaT-KV command entry / its
  [MoaT-KV-]MQTT command topic, actually affects the hardware, and changes the
  state, is your job.
