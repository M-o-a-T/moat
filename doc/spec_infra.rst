--------------
Infrastructure
--------------

One bus client runs gateway firmware which implements a transparent
bidirectional link from the MoaT bus to a serial port. An embedded
computer (Raspberry Pi, ESP32, …) then (un)packetizes the messages
and relays to MQTT.

This allows the daemons which do address assignment, message relaying, and
data collection to operate independently. In particular, each part can be
debugged or restarted without affecting the other components of the MoaT
bus system.


Bus interface
-------------

The code that actually talks to that MoaT bus is started with the script
"moatbus" (when installed) or "./mb" (started from the source directory).

This script implements a couple of subcommands.


gateway
+++++++

Relays between a serial port and MQTT.

Status: done.


addr
++++

Assigns bus addresses and stores them in DistKV.

Status: works but no DistKV integration yet.


flash
+++++

Updates a specific MoaT bus member.

Status: WIP.


data
++++

Reads the nodes' data dictionary, updates the DistKV nodes representing the
data, and relays updates.

Status: not started yet.

