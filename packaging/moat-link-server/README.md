# The MoaT-Link Server

.. start synopsis

MoaT-Link requires a data server for message history, retrieval of
non-retained or possibly-non-existent messages, and communication between
clients.

.. end synopsis

## Rationale

### Message history

MQTT remembers zero or one message per topic. Sometimes it's important to
recover old messages. The MoaT-Link server can record them.

### Message retrieval

MQTT is very good at giving you a topic's message as fast as possible, but
the only way to discover that a messages doesn't exist is to send another
message on a different topic. (Actually, this may not even work on a
multi-threaded server.)

That is not always a good idea. Thus you can just ask the server for it.

### Inter-Client communication

Every program that uses MoaT-Link should connect to a server and broadcast
its location and services. Thus any other MoaT-Link user can connect

### Data recovery

If your MQTT cluster crashes, restoring the status from a day-old backup
may not be the best strategy. The MoaT-Link server will reload the current
state from its log and restore the server's state to just before the crash.
