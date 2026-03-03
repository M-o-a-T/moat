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

`userpass` in the example above is illustrative only; no built-in
`moat.lib.rpc.auth.userpass` method exists at this time.

## Built-in methods

The following auth methods are currently implemented and can be selected via
`auth.modes[].mode`:

- `noop`
  (`moat.lib.rpc.auth.noop.SubAuth`) accepts immediately on both sides.
- `anon`
  (`moat.lib.rpc.auth.anon.SubAuth`) anonymous handshake; the client requests
  it and the server accepts.
- `test`
  (`moat.lib.rpc.auth.test.SubAuth`) test-only method for forcing
  accept/deny/ignore behavior.
- `token`
  (`moat.lib.rpc.auth.token.SubAuth`) token-based authentication.

Custom methods are loaded by `moat.lib.rpc.auth._base.get_auth()`.

## API

The main Auth handler is hooked into {py:class}`moat.lib.rpc.BaseCmdMsg` objects and
its subclasses when an `auth` item is present in the requisite
configuration. Users need not do anything special.

The sub-handlers for individual Auth modes are `BaseCmd` instances that are
set up with their Auth parent and a SubMsgSender pointing to their remote
counterpart.

The `BaseCmdMsg.auth` dynamic auth data object is shared with the `Auth`
handler and forwarded to each `SubAuth` instance as its `auth` attribute.
Custom auth modes can use this for per-connection runtime data (for example,
the current token).

`BaseCmdMsg` also carries an `is_server` flag (default `False`). Listener
handlers set it to `True` for accepted incoming connections, and `Auth` /
`SubAuth` instances can use it to distinguish client and server roles.

Calling `Auth.deny` causes the connection to be rejected unconditionally.

Calling `Auth.accept` accepts the connection. If more than one method
accepts, precedence is by their order in the list of methods (first wins).

Doing neither has the same effect as if the method was not present in the
list.

## Auth Stream App

The `moat.lib.rpc.app.auth.Cmd` app protects command subtrees behind a
single streamed endpoint.

- Direct access to configured sub-apps is blocked.
- The app exposes only one RPC entrypoint: the streamed root command.
- The streamed endpoint runs the regular Auth protocol before forwarding
  nested calls.

Configuration:

- `auth`: required; same structure as on `BaseCmdMsg`.
- `path`: optional path to an existing subtree to expose after auth.
- If `path` is absent, `cfg` must contain the protected app configuration
  (including its own `app` selector).

### Dynamic data

`BaseCmdMsg`.*auth* is a basic `attrdict` which the caller can fill with
relevant data.

## Message format

Auth messages are ordinary MoaT messages, with the first path element set
to ``None``.

Both sides send initial commands to each other with these positional elements
(version 1):

* version#
* server flag
* role name
* a list of supported auth methods

Keyword args may be used, depending on the calling `BaseCmdMsg` class.
The "auth" keyword may be used to transmit initial data to auth methods.

These commands are *not* answered until auth negotiation completes. The
reply consists of one positional argument, the successful auth method (if
auth is successful), but may contain follow-up keywords.
