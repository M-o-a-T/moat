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

    - mode: password
      path: !P admin
      fail_invalid: true

  pass:
  - !P i.ping
```

Dynamic data are the caller's responsibility. In this case:

```
TOK: SomeRandomSecreT
password:
  alice: $ecret
  bob: hunter2
```

## Built-in methods

The following auth methods are currently implemented and can be selected via `mode`:

- `noop`: accepts immediately.
- `anon`: anonymous handshake; the client requests it and the server accepts.
- `test`: test-only method for forcing accept/deny/ignore behavior.
- `token`: token-based authentication.
- `password`: username/password authentication, optionally shielded via
  Diffie-Hellman key exchange (see [below](#password-auth-with-dh-shielding)).

Custom methods are loaded by {py:func}`~moat.lib.rpc.get_auth`.

## Password auth with DH shielding

The `password` auth method supports an optional Diffie-Hellman key
exchange that shields the password digest during transmission.  When
enabled (``dh: true`` in the mode config), the password hash is
encrypted under a DH-derived shared secret before it crosses the wire.

All cryptographic operations use the vetted [`cryptography`](https://cryptography.io)
package — no custom crypto is rolled.

### Cryptographic primitives

| Component | Algorithm |
|-----------|-----------|
| Key exchange | Diffie-Hellman, MODP Group 14 (2048-bit, RFC 3526) |
| Key derivation | HKDF-SHA256, info = `b"moat-rpc-password-dh"`, 32-byte output |
| Symmetric encryption | AES-256-GCM (12-byte nonce, authenticated) |
| Password hashing | SHA-256 |

### Configuration

Set ``dh: true`` on both client and server mode configs:

```
auth:
  modes:
  - mode: password
    dh: true          # shield password via DH
    fail_invalid: true  # (server) reject bad credentials
```

Both sides must agree on the ``dh`` setting.  If the client has ``dh: false``
(or omits it), the plain path is used — the password hash is sent
directly, relying on TLS for confidentiality.

### Handshake flow

**Phase 1 — key exchange:**

```
Client → Server:  (client_public_key_PEM,)
Server → Client:  (server_public_key_PEM, nonce, encrypted_challenge)
```

The server generates a DH keypair, derives the shared secret from the
client's public key, and uses the HKDF-derived key to AES-GCM-encrypt a
random 12-byte challenge.  It returns its public key, the nonce, and the
ciphertext.

**Phase 2 — credential submission:**

```
Client → Server:  (username, enc_nonce, encrypted_password_hash, challenge_response)
```

The client decrypts the challenge, encrypts the SHA-256 password hash
under the shared key, and sends the username along with the ciphertext,
a fresh nonce, and the decrypted challenge (proving possession of the
shared secret).

The server verifies the challenge response, decrypts the password hash,
compares it against the expected hash with `hmac.compare_digest`, and
accepts or denies accordingly.

### Graceful fallback

If DH negotiation fails on the client side (server returns `None`,
malformed response, or an exception occurs), the client automatically
falls back to the plain submission path:

```
Client → Server:  (username, password_hash)
```

This relies on the underlying TLS transport for confidentiality.  The
fallback is transparent — the server sees a standard plain-mode
credential submission.

### Secret hygiene

- The raw DH shared secret and the derived AES key are held only in
  local variables during the handshake.
- After phase 2 completes (success or failure), the server clears
  `_dh_key` and `_dh_challenge` via `_cleanup_dh_state()`.
- The client deletes the shared secret and derived key after sending.
- Neither the shared secret nor the derived key is ever logged.
- DH parameters (2048-bit MODP group) are generated once and cached at
  module level; ephemeral keypairs are generated per connection.

## API

The main Auth handler is hooked into {py:class}`~moat.lib.rpc.BaseCmdMsg` objects and
its subclasses when an `auth` item is present in the requisite
configuration. Users need not do anything special.

The sub-handlers for individual Auth modes are {py:class}`~moat.lib.rpc.BaseCmd`
instances that are set up with their Auth parent and a SubMsgSender
pointing to their remote counterpart.

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

The {py:class}`moat.lib.rpc.app.auth.Cmd` app protects command subtrees
that are located behind a single streamed endpoint.

- Direct access to configured sub-apps is blocked.
- The app exposes only one RPC entrypoint: the streamed root command.
- The streamed endpoint runs the regular Auth protocol before forwarding
  nested calls.

Configuration:

- `auth`: required; same structure as on {py:class}`~moat.lib.rpc.BaseCmdMsg`.
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
* server flag (bool)
* name
* a list of supported auth methods

Keyword args may be used, depending on the calling `BaseCmdMsg` class.
The "auth" keyword may be used to transmit initial data to auth methods.

The Auth command is answered when auth negotiation completes. The reply
consists of one positional argument (name of the successful auth method)
and may contain follow-up keywords.

Auth failure is conveyed by raising an exception.

## Stream-based auth

`rpc_on_rpc()` accepts an optional `auth` keyword argument. When provided,
the CmdStream runs an auth negotiation handshake before becoming available
to the caller. After auth completes, `cmdo.auth` contains the resulting
`SubAuth` instance (or an exception is raised if auth was denied).

One side must be designated as the server by passing `is_server=True`;
the other side is the client (the default).

```python
async with msg.stream(), rpc_on_rpc(
    MyHandler(), msg, auth=auth_cfg, is_server=True
) as cmdo:
    # cmdo.auth is now populated
    result = await MsgSender(cmdo).cmd("some_command", ...)
```

The auth configuration is an `attrdict` with an `auth` key containing
`modes` (list of auth method configs) and method-specific parameters.
For the built-in `test` method, set `ok: true` to accept or `ok: false`
to deny.
