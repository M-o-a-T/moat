# Error Handling and Notifications

MoaT-Link stores error states and sends notifications for relevant events.

## Error Recording

Errors are recorded via `moat.link.client` methods:

- `e_exc`: report an exception.
- `e_info`: report a non-exception problem.
- `e_ack`: acknowledge an active error.
- `e_ok`: mark an error path as resolved.

Raw entries are stored below `error.raw.<path>`, where `<path>` identifies the
affected data branch.

## Filtering and Notification

Updated raw entries are processed using `error.filter.*` rules that match on
the path and content. A filter can decide whether to suppress, delay, or emit a
notification.

Notification output is assembled from the matching filtered entry.
