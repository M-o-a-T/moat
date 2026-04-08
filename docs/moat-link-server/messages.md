# Server commands

## Basics

Command contents are described via OpenAPI.

There are no "methods"

Initially both client and server send an Auth command `:n`.

Further commands may be exchanged once the Auth (and any
authorization required by it) is complete.

## Command details

### `:n`

Both sides independently call this method to tell the other side about
them and their requirements for proceeding.

The message includes a list of auth methods the remote side needs to
support. Both sides MUST perform one of these schemes successfully
before replying to this message.

An Auth message MAY contain auth data in anticipation of the server's
request. Thus if client A connects to server B:

> A\>B (1) Auth(1, client\_A,server\_B, True, token="foobar")
> B\>A (1) Auth(2, server\_B,client\_A, "token")
> A\<B (1) (True)
> B\<A (1) (True)

negotiates protocol version 1; the client successfully presented
the token "foobar" for the "token" login method.

### `:n.X`

Auth subcommand for method X, initiated by the . Should be streamed if the interaction
comprises more than one message per direction.


#### i.bye

Controlled shutdown. Sent by the server to tell the client to please
reconnect to someplace else. The client should delay replying until it
has connected to a different server.

#### d.get

Argument: Path.

Reply: the dataset at this path, consisting of the actual data and the
metadata.
