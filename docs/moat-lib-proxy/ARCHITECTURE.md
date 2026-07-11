# Architecture — moat.lib.proxy

Object proxying for serialization-by-reference: type-tag objects so they
survive codec transport by registered name, rather than being serialized by
value.

## Files

- `_impl.py` — `Proxy`/`DProxy`/`_CProxy`, `as_proxy` decorator/registrations.
- `_proxy.py` — proxy mechanics.

## Mechanism

`as_proxy(name, cls=None, …)` registers a type under a string name. When such
an object crosses a `moat.lib.codec` boundary, it is encoded as a small
`(name, state)` record rather than its full value; the peer looks up the name
and reconstructs a live proxy referring to the original object's identity.

This preserves **object identity and live behavior** across the transport: a
proxy handed to the remote side stands in for the local object, and method
calls / attribute access can round-trip back. Crucial for the RPC system
where remote command trees hand back references to sub-objects (e.g. a
specific Modbus unit, a battery cell, an open file).

`Proxy`/`DProxy`/`_CProxy` are the proxy flavors (direct / deferred /
cached). `_CProxy` caches reconstructed objects.

## Standard registrations

`moat.lib.codec.errors` registers all standard Python exceptions this way
(`as_proxy("_rErrS", SilentRemoteError)`, …) so a raised exception on one side
re-materializes as the same exception type on the other.

## Consumers

- `moat.lib.rpc` — command trees return proxies to remote sub-objects;
  `Caller` results may be proxies.
- `moat.lib.codec` — the proxy record is just another codec extension.
- `moat.ems.battery` — `BatteryAlert` subclasses registered via `as_proxy` so
  alerts cross the micro/RPC link intact.
- `moat.micro` — `app/_sys.py:cmd_unproxy` lets the client drop a proxy;
  `cmd_eval` returns proxies for introspected objects.

## Naming constraint

Proxy names must not start with `_` or be `""`/`"-"` (enforced in
`micro/app/_sys.py:cmd_unproxy`) — reserved/internal.
