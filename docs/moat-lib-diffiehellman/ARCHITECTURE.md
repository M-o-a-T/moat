# Architecture — moat.lib.diffiehellman

Diffie-Hellman key exchange for RPC authentication.

## Implementation (`diffiehellman/_impl.py`)

Implements ephemeral Diffie-Hellman so two RPC peers can establish a shared
secret over an untrusted channel without prior shared material. The derived
secret authenticates subsequent RPC traffic (challenge/response, encrypted
handshake state).

## Consumers

`moat.lib.rpc.auth` uses this for the authenticated `Hello` handshake
exchanged over the RPC link — see `moat-link/ARCHITECTURE.md` (`Hello` in
`link/hello.py`, token/anon modes) and `moat-lib-rpc/ARCHITECTURE.md`.
