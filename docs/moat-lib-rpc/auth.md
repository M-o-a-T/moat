# Authentication/Authorization

MoaT-RPC links might need some form of access control.

## Structure

The Auth handler is an async context manager. It is started with a BaseMsg
instance to the remote side, which it connects to a BaseCmdMsg handler
whose initial root is the auth handler itself.

Successful authorization causes the handler's root to be set to the "real"
root, or whichever part the auth method specifies in its `path` config
attribute.

The context manager yields a MsgSender that connects back to the remote side.


## Configuration

Config is split into static and dynamic data.

Static parameters:

```
auth:
  modes:
    - mode: anon
      path: !P public

    - mode: token
      name: TOK

    - mode: userpass
      data: users
      path: !P admin

  pass:
  - !P i.ping
```

Dynamic data are the caller's responsibility. In this case:

```
TOK: SomeRandomSecreT
users:
  fred: FlInTsToNe123
```

## API

The main Auth handler is used as
```
from moat.lib.rpc import Auth
from moat.lib.micro import idle

class SomeIncomingHandler(MsgHandler):
    async def accept(self, stream:BaseMsg, *, task_status):
        async with Auth(self.cfg.auth, stream) as sdr:
            self.fwd[conn_id] = sdr  # might be named or indexed
            task_status.started()
            await idle()
```
The `SomeIncomingHandler.handle` method should forward to `self.fwd` in
some form. An app that accepts TCP connections might index its connections
by a randomly generated ID, or simply number them consecutively.

The sub-handlers for individual Auth modes are `BaseCmd` instances that are
set up with their Auth parent and a SubMsgHandler pointing to their remote
counterpart. They should call `accept`, `fail` or `deny` after determining
the result.
