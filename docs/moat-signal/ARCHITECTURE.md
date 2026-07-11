# Architecture — moat.signal

Standalone async client for the **Signal** messenger app, wrapping the
**signal-cli JSON-RPC REST API**. Handles sending messages/attachments/
reactions, group management, profile updates, and account
registration/verification.

## Key types (`signal/api.py`, 555 lines)

- **`SignalClient`** — constructed with `endpoint` (JSON-RPC URL),
  `account` (phone number), optional `auth` (basic-auth tuple), and `**kw`
  forwarded to `httpx.AsyncClient`. Core private method `_jsonrpc(method,
  params)` builds a JSON-RPC 2.0 envelope (UUID request id, injects
  `account`), POSTs via httpx, raises `SignalError` on RPC errors. Public
  methods: `version`, `send_message` (text + file/byte attachments + mentions;
  splits recipients into contacts/groups), `update_group` (create/configure
  groups with permissions, links, expiry, avatar), `quit_group`, `list_groups`,
  `get_group`, `join_group`, `update_profile`, `send_reaction`,
  `get_user_status`, `register`, `verify`, `get_recipients`.
- **`SignalError(Exception)`** — raised on any RPC failure.
- Helpers: `bytearray_to_rfc_2397_data_url(…)`, `get_attachments(files, bytes)`.

## Integration

**None.** `api.py` imports only standard-library modules plus `httpx`,
`jmespath`, `magic`, and `packaging` — zero `moat.*` imports. A fully
standalone, vendored async Signal client with no coupling to link, RPC,
micro, kv, or any other MoaT subsystem.

## Entry points

Library-style only — instantiate `moat.signal.SignalClient(endpoint, account,
…)` and call its async methods. There is no `_main.py`/CLI in `moat/signal/`;
the package re-exports `SignalClient` and `SignalError` from `api.py`.
