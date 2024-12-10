===============
Server commands
===============

Basics
******

Command contents are described via OpenAPI.

There are no "methods"

Initially both client and server send an "hello" command.

Further commands may be exchanged once both the "hello" and
any required authorization is complete.

Command details
***************

hello
+++++

The client calls this to tell the server about itself.
Used for status display.

The server replies with its detail/generic status info.

auth
++++

The client sends a sub-command of "auth" to authorize itself.

Depending on the auth protocol, the message exchange required for
authentication may be streamed.

The client may speculatively send e.g. an "auth mqtt" command if it has
obtained the auth token via MQTT. Otherwise it should wait for the server's
Hello message, as that tells it about the supported and/or required auth
methods.

Failed auth may cause the server to disconnect.

auth mqtt
---------

Not streamed.

The single argument is the current magic key, as read from MQTT.

On error the server replies with an error message.

bye
---

Controlled shutdown. Sent by the server to tell the client to please
reconnect someplace else. The client should only reply when it is
ready to tear down the link.


data get
--------

Argument: Path.

Reply: the dataset at this path.


