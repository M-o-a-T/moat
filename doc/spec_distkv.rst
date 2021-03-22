Device attributes
=================

Device data are stored in DistKV, by default under ``:.distkv.moat.bus``.

The first level has "bus", "type" and "devices" nodes.

Clients
-------

Clients are named by their serial#. The bus master is responsible for
storing the bus name, client number and presence status to their node.
The client node should be considered read-only by everybody else.

The client may have a "type" node which either contains a download of the
device's data dictionary or the path to an entry under "type". The server
is responsible for fetching the type node.

The client may have an "info" node containing human-readable data, like the
client's name and location.

The client should have a "data" node containing sub-nodes with the actual
data from, or to, the client, structured as per the client's type.

More complex clients will also have a "control" node with the same
structure, containing attributes that control the client. The server shall
not write to the control sub-hierarchy.

A similar "status" hierarchy is used for mirroring the values of written
data. E.g., if ``data.port.12`` is a wired-AND output port that's set to
``True``, ``status.port.12`` might reflect the port's actual state.
However, if the same port is set to be an input port, its value should
show up in ``data.port.12``, and the value under ``status`` should not
exist.

Buses
-----

MoaT Buses support to three servers. If there are multiple serves on a bus,
they must coordinate which one is currently responsible, possibly by using
a DistKV Actor.

MoatBus servers are not monolithic; they can consist of several
subprocesses. This document describes the actual bus attachment.

Gating from the bus to MQTT should be idempotent. If multiple attachment
points to a bus exist, secondary servers should monitor both and take over
if packets on one bus do not show up on the other after a suitable delay
which again should be coordinated via an Actor.

A bus DistKV node contains user data and the MQTT path to use. Direct
sub-nodes are named by the host running the bus attachment and contain a
port type ("serial") and some port-related data (serial: device, speed).

Types
-----

All client nodes carry a data dictionary. This dictionary may either
contain the actual device description or refer to a path in the "types"
hierarchy. The contents are identical.

The data dictionary specifies addressable data items. It doesn't say
whether to store them in the ``data``, ``control``, or ``state``
subhierarchies, nor whether to collate entries to dictionaries or spread
them to distinct nodes.


