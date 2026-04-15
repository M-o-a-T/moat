# Error Handling and Notifications

MoaT-Link stores error states and sends notifications for relevant events.

## Error Recording

Errors are recorded via `moat.link.client` methods:

- {py:meth}`moat.link.client.LinkSender.e_exc`: report an exception.
- {py:meth}`moat.link.client.LinkSender.e_info`: report a non-exception problem.
- {py:meth}`moat.link.client.LinkSender.e_ack`: acknowledge an active error.
- {py:meth}`moat.link.client.LinkSender.e_ok`: mark an error path as resolved.

Raw entries are stored below `error.raw.<path>`, where `<path>` identifies the
affected data branch.

## Filtering and Notification

Updated raw entries are processed using `error.filter.*` rules that match on
the path and content. A filter can decide whether to suppress, delay, or emit a
notification.

Notification output is assembled from the matching filtered entry.
