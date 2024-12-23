===============
Server commands
===============

Basics
******

Command contents are described via OpenAPI.

There are no "methods"

Initially both client and server send an "i.hello" command.

Further commands may be exchanged once both the "i.hello" (and
any authorization required by it) is complete.


Command details
***************

i.hello
+++++++

Both sides independently call this method to tell the other side about
them and their requirements for proceeding.

The message includes a list of auth methods the remote side needs to
support. Both sides MUST perform one of these schemes successfully before
replying to this message.

A Hello message MAY contain auth data in anticipation of the server's request.
Thus:

	A>B  (1) i.hello(1.1, client_A,server_B, True, token="foobar")
	B>A  (1) i.hello(1.2, server_B,client_A, "token")
	A<B  (1) (True)
	B<A  (1) (True)

negotiates protocol version 1.2 and a client that successfully presented
the token "foobar" for login.


i.auth.X
++++++++

The client sends this subcommand to authorize itself.

Depending on the auth protocol ("X"), the message exchange required for
authentication may be streamed.

i.auth.token
------------

Not used.

The single argument is the current magic key, as read from MQTT.

On error the server replies with an error message.

i.bye
-----

Controlled shutdown. Sent by the server to tell the client to please
reconnect to someplace else. The client should delay replying until it has
connected to a different server.


d.get
-----

Argument: Path.

Reply: the dataset at this path, consisting of the actual data and the
metadata.

