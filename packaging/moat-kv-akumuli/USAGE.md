# Using MoaT-KV-Akumuli

Run "moat kv akumuli monitor server" to connect to the specified server.

See "moat util cfg kv.akumuli" for configuration options.

## Data structure

On disk, the path to the port is ".moat kv akumuli SERVER NAME…" by
default. All attributes are also looked up in the higher nodes, so you
can set per-type values easily.

### Attributes

- server: a dict with host and port. Set by `moat kv akumuli server`.
- metric: the Akumuli metric to use. Inherited.
- keys: a dict with keys that a value shall have. Inherited.
- src: An array. The path to the Moat-KV value which shall be stored.

## Command line

<div class="program">

moat kv akumuli

</div>

The main entry point for this extension.

<div class="program">

moat kv akumuli set

</div>

Print or modify port settings.

This is a shortcut for `… attr` that evaluates various attributes and
lets you easily change more than one at a time.

<div class="option">

-m, --metric METRIC

Set the metric to use in this subtree.

This option cannot be used on top or server level.

</div>

<div class="option">

-k, --key name=value

Add a key. An empty value deletes the key.

This option can be used more than once.

</div>

<div class="option">

-s, --src "source path"

Set the value to record.

This option cannot be used on top or server level.

</div>

<div class="option">

-e, --eval

The value of 'src' shall be evaluated.

</div>

<div class="option">

path

The path to the node to be modified.

</div>

<div class="program">

moat kv akumuli list

</div>

Lists the names below of a subtree.

<div class="option">

path

The path to the node to be shown.

</div>

<div class="program">

moat kv akumuli get

</div>

Displays the data at a node.

<div class="option">

-r, --recursive

Lists the subtree starting here.

</div>

<div class="option">

path

The path to the node to be shown.

</div>
