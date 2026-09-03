# Error Handling and Notifications

MoaT-Link stores error states and sends notifications for relevant events.

## Error Recording

Errors are recorded via `moat.link.client` methods:

- {py:meth}`moat.link.client.LinkSender.e_exc`: report an exception.
- {py:meth}`moat.link.client.LinkSender.e_info`: report a non-exception problem.
- {py:meth}`moat.link.client.LinkSender.e_ack`: acknowledge an active error.
- {py:meth}`moat.link.client.LinkSender.e_ok`: mark an error path as resolved.

Raw entries are stored below `error.<path>`, where `<path>` identifies the
affected data branch.  Each entry is a dict containing `msg`, `level`
(1–5), optional `exc`/`bt` (exception/backtrace), `n` (occurrence count),
`first` (timestamp of first occurrence), and auxiliary `data`/`aux`.

## Error Mirroring

The `ErrorMirror` class ({py:class}`moat.link.notify.ErrorMirror`) watches
the `error.*` subtree and mirrors qualifying entries to `notify.*` so that
the `Notify` runner forwards them to backends (ntfy.sh, etc.).

Mirroring rules are **not** statically configured.  Instead, they are read
dynamically from a **notify-vecs** subtree stored below `conv.*` in the link
data tree — the same pattern used by the Venus gateway's `codec_vecs`.

### Configuration

Set `link.notify.vecs` to a path below `conv.*` that holds the mirroring
rules:

```yaml
# moat/link/notify/_cfg.yaml
vecs: !P notify_rules
```

When `vecs` is not set, all errors at warning level or higher are mirrored.

### Rule Tree Structure

Each node in the notify-vecs tree corresponds to a path prefix in the
error subtree.  Rules are collected with {py:meth}`moat.link.node.Node.collect`,
which merges data from all matching wildcard branches — more specific
branches override less specific ones.

A rule dict may contain:

- `min_level` — minimum severity to mirror (`"debug"`, `"info"`,
  `"warning"`, `"error"`, `"fatal"`; default `"warning"`).
- `skip` — set to `True` to suppress mirroring for this branch.
- `prio` — override the notification priority.
- `title` — override the notification title.

Example: require `error` level globally, but allow `warning` under
`run.other`:

```
conv.notify_rules                 → {"min_level": "error"}
conv.notify_rules.run.other      → {"min_level": "warning"}
```

### Resolution

When an error is cleared (`ok=True` or the entry is deleted), the
corresponding notification is removed from the `notify.*` subtree.

## Notification Forwarding

The `Notify` class ({py:class}`moat.link.notify.Notify`) watches the
`notify.*` subtree and forwards messages to configured backends.  Run it
with `moat link notify run`.  Run the mirror with `moat link notify mirror`.
