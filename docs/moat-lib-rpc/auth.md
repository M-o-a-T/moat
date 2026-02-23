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
  - !P i.hello
```

Dynamic data are the caller's responsibility. In this case:

```
TOK: SomeRandomSecreT
users:
  fred: FlInTsToNe123
```

## API

The main Auth handler is hooked into {py:class}`BaseCmdMsg` objects and
its subclasses when an `auth` item is present in the requisite
configuration. Users need not do anything special.

The sub-handlers for individual Auth modes are `BaseCmd` instances that are
set up with their Auth parent and a SubMsgSender pointing to their remote
counterpart.

Calling `Auth.deny` causes the connection to be rejected unconditionally.

Calling `Auth.accept` accepts the connection. If more than one method
accepts, precedence is by their order in the list of methods (first wins).

Doing neither has the same effect as if the method was not present in the
list.

### Dynamic data

`BaseCmdMsg`.*auth* is a basic `attrdict` which the caller can fill with
relevant data.
