# Error handling and Notifications

Sometimes, things go wrong. MoaT-Link has a mechanism to record error
conditions and to alert the user.

## Error recording

Errors are recorded via moat.link.client's e_* methods:

* TODO: link to each, and a one-paragraph documentation of their semantics

They are stored under the error.raw.XX path where XX is the path of whichever
data item is uniquely responsible for the problem.

Next, updated errors get filtered via the error.filter.* hierarchy. We collect
entries matching the XX path and use them to filter the error, as per some
criteria (age, severity, …). Filters should be named "NN name". Let's check
the web if we can find a simple YAML-based interpreter that can do basic
equality, comparison, and and/or/not operations, but otherwise write our
own.

In addition to the filter we need an output section that assembles the notification
message.
