# The MoaT-KV command

MoaT-KV extends the MoaT command line tool with the `moat kv` subcommand
which provides various sub- and sub-sub-commands to run and control your
server.

## moat.kv

<div class="program">

moat kv

</div>

The main entry point for all commands.

<div class="option">

-h, --host \<address\>

The address to connect to. Defaults to `localhost`.

This setting is also available as the `connect.host` configuration
setting.

</div>

<div class="option">

-p, --port \<port\>

The port to connect to. Defaults to 27586.

This setting is also available as the `connect.port` configuration
setting.

</div>

<div class="option">

-a, --auth \<params\>

Parameters for authorizing this client. Use `=file` to load the data
from a file, or `method data=value…` to provide them inline.

The default is `_anon`, i.e. no authorization.

</div>

<div class="option">

-m, --metadata

The results of many commands will include the metadata associated with
the entry or entries in question. This allows you to safely modify a
value.

</div>

<div class="program">

moat kv server

</div>

Run the MoaT-KV server.

A MoaT-KV server holds all data and syncs with all other MoaT-KV
servers. You can't run `moat kv` unless you have at least one running
server (except for the "server" and "dump" subcommands).

There is no separate option to set the address for clients to connect
to; use `server.bind_default.port=57589` (or your own port number) to
change it from the default of `27589`, or use a configuration file.

<div class="option">

-l, --load \<file\>

Pre-load the saved data from this file into the server before starting
it.

**Do not use this option with an out-of-date savefile.**

</div>

<div class="option">

-s, --save \<file\>

Log all changes to this file. This includes the initial data.

This option is only used for testing. Use `moat kv log dest` in
production use.

</div>

<div class="option">

-i, --incremental

Don't write the complete state to the save file.

This option is of limited usefulness and only used for testing. Use
`moat kv log dest -i` in production.

</div>

A network of servers needs to contain some data before it becomes
operational. When starting the first server, you can use an initial

<div class="option">

-I, --init \<value\>

Initialize the server by storing this value in the root entry.

This option is only used for testing. Create initial content with
`moat kv dump init` for production use.

</div>

<div class="option">

-e, --eval

Evaluate the initial value, as a standard Python expression.

This option is only used for testing.

</div>

You can also use `moat kv data set` to update this value later.

<div class="option">

name

</div>

Each MoaT-KV server requires a unique name. If you recycle a name, the
old server using it will die (unless your network is segmented – in that
case, one or both will terminate some random time after the networks are
reconnecting, and you'll get inconsistent data). So don't do that.

<div class="program">

moat kv data

</div>

Basic data access.

<div class="option">

path

Access the entry at this location.

</div>

<div class="program">

moat kv data get

</div>

Read a MoaT-KV value.

If you read a sub-tree recursively, be aware that the whole subtree may
be read before anything is printed. Use the `monitor --state` subcommand
for incremental output.

<div class="option">

-r, --recursive

Print all entries below this entry.

</div>

<div class="option">

-d, --as-dict \<text\>

When you use this option, the data is printed as a dictionary. The
argument of this option controls which key is used for the actual value;
this string should not occur as a path element.

The customary value to use is a single underscore.

Using this option in conjunction with `--recursive` requires keeping the
whole data set in memory before starting to print anything. This may
take a long time or eat a lot of memory.

When this option is not used, the result is emitted as a list. Each item
consists of a dictionary with a single entry; the key is the item's
path. Some YAML parsers might not like that.

</div>

<div class="option">

-m, --mindepth \<integer\>

When printing recursively, start at this depth off the given path.

The default is zero, i.e. include the entry itself.

</div>

<div class="option">

-M, --maxdepth \<integer\>

When printing recursively, stop at this depth (inclusive).

The default is to print the whole tree. Use `1` to print the entry
itself (assuming that it has a value and you didn't use `--mindepth=1`)
and its immediate children.

</div>

<div class="program">

moat kv data list

</div>

List MoaT-KV values.

This command is basically like `moat kv data ‹path› get`, except that
`--recursive` and `empty` are always set. `mindepth` and `maxdepth`
default to 1.

<div class="option">

-r, --recursive

Print all entries below this entry.

</div>

<div class="option">

-d, --as-dict \<text\>

When you use this option, the data is printed as a dictionary. The
argument of this option controls which key is used for the actual value;
this string should not occur as a path element.

The customary value to use is a single underscore.

Using this option in conjunction with `--recursive` requires keeping the
whole data set in memory before starting to print anything. This may
take a long time or eat a lot of memory.

</div>

<div class="option">

-m, --mindepth \<integer\>

When printing recursively, start at this depth off the given path.

The default is zero, i.e. include the entry itself.

</div>

<div class="option">

-M, --maxdepth \<integer\>

When printing recursively, stop at this depth (inclusive).

The default is to print the whole tree. Use `1` to print the entry
itself (assuming that it has a value and you didn't use `--mindepth=1`)
and its immediate children.

</div>

<div class="program">

moat kv data set

</div>

Store a value at some MoaT-KV position.

If you update a value, you should use `--last` (preferred) or `--prev`
(if you must), to ensure that no other change collides with yours.

When adding a new entry, use `--new` to ensure that you don't
accidentally overwrite something.

<div class="option">

-v, --value \<value\>

The value to store. This option is mandatory.

</div>

<div class="option">

-e, --eval

Treat the `value` as a Python expression, to store anything that's not a
string.

</div>

<div class="option">

-l, --last \<node\> \<count\>

The chain link which last modified this entry.

</div>

<div class="option">

-n, --new

Use this option instead of `--last` or `prev` if the entry is new, or
has been deleted.

</div>

<div class="option">

-p, --prev \<value\>

The value which this entry needs to have in order to be affected.

Try not to use this option; `--last` is much better.

This value is also affected by `--eval`.

</div>

<div class="program">

moat kv data delete

</div>

Delete the value at some MoaT-KV position.

If you delete a value, you should use `--last` (preferred) or `--prev`
(if you must), to ensure that no other change collides with your
deletion.

Recursive changes only check the entry you mention on the command line.

<div class="option">

-l, --last \<node\> \<count\>

The chain link which last modified this entry.

</div>

<div class="option">

-e, --eval

Treat the `value` as a Python expression, to store anything that's not a
string.

</div>

<div class="option">

-p, --prev \<value\>

The value which this entry needs to have in order to be affected.

Try not to use this option; `--last` is much better.

This value is also affected by `--eval`.

</div>

<div class="program">

moat kv data monitor

</div>

Monitor changes to the state of an entry, or rather its subtree.

<div class="option">

-s, --state

Before emitting changes, emit the current state of this subtree.

A flag entry will be printed when this step is completed.

</div>

<div class="option">

-o, --only

Only emit the value. This mode is ideal for monitoring an entry with a
script or similar.

This mode will only watch a single entry, not the whole tree. The
command will exit silently if the value is deleted or, when `--state` is
used, doesn't exist in the first place.

</div>

> [!NOTE]
> The current state may already include updates, due to MoaT-KV's
> asynchonous nature. You should simply replace existing values.

<div class="option">

-m, --msgpack

Write the output as `MsgPack` data. XXX TODO

The default is to use YAML.

</div>

<div class="program">

moat kv data update

</div>

Stream a list of changes from standard input to MoaT-KV. Paths in the
data set are interpreted relative to the path given.

<div class="option">

-m, --msgpack

Interpret the input as `MsgPack` data. XXX TODO

The default is to use YAML. XXX TODO

</div>

<div class="program">

moat kv control

</div>

Control your server. XXX TODO

<div class="program">

moat kv log

</div>

Control logging of changes on the server.

<div class="program">

moat kv log dest

</div>

Set the file to log to. The old file is closed as soon as the new file
is ready (i.e. the current state is saved).

<div class="option">

-i, --incremental

The save file will only contain changes, but not the current state.

</div>

<div class="option">

path

The file to write to. Note that this file is on the server.

</div>

<div class="program">

moat kv log save

</div>

Save the current state of the server to this file.

<div class="option">

path

The file to write to. Note that this file is on the server.

</div>

<div class="program">

moat kv log stop

</div>

Stop logging.

<div class="program">

moat kv auth

</div>

Set up and change client authorization.

If you have never setup authorization, this sub-subcommands' `--help`
options may not work. Use `-m root` as a workaround. XXX TODO

<div class="option">

-m, --method \<name\>

Affect the named method.

MoaT-KV supports multiple authorization methods. The default is the one
that has been changed to with `moat kv auth init`.

If you want to do anything with authorization, you'll need to use this
flag to set up the initial users.

See <span class="title-ref">Auth</span>.

</div>

<div class="program">

moat kv auth init

</div>

Set up this method.

<div class="option">

-s, --switch

Actually swtich to using this method. This is the default for initial
set-up.

</div>

<div class="program">

moat kv auth list

</div>

List configured auth methods.

XXX TODO

<div class="program">

moat kv auth user

</div>

Manage MoaT-KV users.

Each authorization method has its own schema for validating users.

<div class="program">

moat kv auth user add \<key\>=\<value\>…

</div>

Add a new user.

Example:
`moat kv -a root auth -m password user add name=foo password=barbaz`

The identifier which you'd use to subsequently refer to that user is
printed when this command completes.

<div class="option">

\<key\>=\<value\>

Set an auth-specific parameter. If you write `password?` instead of
`password=SomeSecret`, you tell MoaT-KV to read the actual data from the
terminal (without echo) so that it won't show up in your history.

</div>

<div class="program">

moat kv auth user mod \<ident\> \<key\>=\<value\>…

</div>

Modify a user.

<div class="option">

\<ident\>

The identifier MoaT-KV has assigned to the user.

</div>

<div class="option">

\<key\>=\<value\> Set an auth-specific parameter.

</div>

<div class="program">

moat kv auth user param \<ident\> \<type\> \<key\>

</div>

Modify a user's setting.

<div class="option">

\<ident\>

The identifier MoaT-KV has assigned to the user.

</div>

<div class="option">

\<type\>

The type of setting to modify. The server interprets "acl" and "conv".

</div>

<div class="option">

\<key\>

The type-dependent setting to use as stored in MoaT-KV. For ACLs the
relevant record is added with `moat kv acl set <key> …`, for data
conversion `moat kv codec convert <key> …`.

</div>

<div class="program">

moat kv auth user auth

</div>

Check that authorizing a user works.

XXX TODO seems broken

<div class="option">

options…

Whichever auth options you'd normally use in `moat kv -a TYPE …`.

</div>

<div class="program">

moat kv auth user get

</div>

Dump data of a user.

<div class="option">

-c, --chain \<int\>

</div>

The chain length to return, for subsequent modification.

<div class="option">

ident

The user identifier, as reported by `add`.

</div>

<div class="program">

moat kv auth user list

</div>

List users.

XXX TODO add verbosity

<div class="program">

moat kv type

</div>

Set up MoaT-KV's type control: verify the data that clients write.

See `translator` for details.

<div class="program">

moat kv type get

</div>

Retrieve a type entry.

<div class="option">

-y, --yaml

Emit the schema as YAML data. Default: JSON.

</div>

<div class="option">

-s, --script \<filename\>

Save the script to this file. Default: include in the output.

</div>

<div class="option">

-S, --schema \<filename\>

Save the schema to this file. Default: include in the output.

</div>

<div class="option">

name…

The type data to retrieve.

</div>

<div class="program">

moat kv type set

</div>

Add or modify a type entry.

For setting up a type, you need at least two good and one bad test
value. (If there's only one possible good value, you don't need the
entry; if there's no bad value you don't need the type check.)

Type checks accumulate: Both 'good' and 'bad' test values for "int
percent" must be accepted by "int".

Tests can use Python code, a JSON schema, or both. In the latter case
the schema is tested first.

To modify a record, use `moat kv type get <path>… > <tempfile>`, edit
the tempfile, then restore with
`moat kv type set -d <tempfile> <path>…`.

<div class="option">

-y, --yaml

Read the schema as YAML. Default: JSON.

</div>

<div class="option">

-s, --script \<filename\>

Load the script from this file. Default: no script.

</div>

<div class="option">

-S, --schema \<filename\>

Load the schema from this file. Default: no schema.

</div>

<div class="option">

-g \<value\>

A known-good value to test the codec. It will be Python-evaluated.

</div>

<div class="option">

-b \<value\>

A known-bad value to test the codec. It will be Python-evaluated.

</div>

<div class="option">

-a, --all

Load the complete record from the `script` file.

</div>

<div class="option">

name…

The type data to set.

</div>

<div class="program">

moat kv type match

</div>

Read, set or delete type matches, i.e. which part of your MoaT-KV tree
is constricted by which type.

<div class="option">

-t, type \<name\>

The type name to use. Use multiple
<span class="title-ref">--type</span>\` options to access subtypes. Skip
this option to display which type corresponds to the given path.

</div>

<div class="option">

-d, --delete

Delete the match record instead of printing it.

</div>

<div class="option">

path…

The MoaT-KV entry to affect. Path elements '+' and '#' match exactly-one
and one-or-more subpaths. The most specific path wins.

</div>

<div class="program">

moat kv codec

</div>

Set up codecs: manipulate the data that clients see, sort of like a
database view.

Codecs consist of code that encodes, i.e. converts to the user's view,
and decodes, i.e. converts to the server's storage.

Codecs cannot translate path names, or access other entries. The decoder
may modify an existing entry (or rather, use the currently-stored
version when assembling an entry's new value).

Unlike types, the codec hierarchy is strictly for convenience.

<div class="program">

moat kv codec get

</div>

Retrieve information about a codec, including its scripts.

<div class="option">

-e, --encode \<file\>

The file which the encoder's Python code is written to.

If this option is not used, the code is part of the script's output.

</div>

<div class="option">

-d, --decode \<file\>

The file which the decoder's Python code is written to.

If this option is not used, the code is part of the script's output.

</div>

<div class="option">

-s, --script \<file\>

The YAML file to which to write any other data.

This file will also contain the scripts, if not stored otherwise.

</div>

<div class="option">

\<name\>

The name of the codec group from which this codec should be retrieved.

</div>

<div class="option">

\<path\>

The MoaT-KV entry that would be affected. Path elements '+' and '#'
match exactly-one and one-or-more subpaths. The most specific path wins.

</div>

<div class="program">

moat kv codec set

</div>

Add or modify a codec.

To modify a codec, use `moat kv codec get <path>… > <tempfile>`, edit
the tempfile, then restore with
`moat kv codec set -d <tempfile> <path>…`.

<div class="option">

-e, --encode \<file\>

The file which contains the encoder's Python code.

</div>

<div class="option">

-d, --decode \<file\>

The file which contains the decoder's Python code.

</div>

<div class="option">

-i, --in \<source\> \<dest\>

A pair of test values for the decoding branch of the codec. Both are
`eval`-uated.

</div>

<div class="option">

-o, --out \<source\> \<dest\>

A pair of test values for the encoding branch of the codec. Both are
`eval`-uated.

</div>

<div class="option">

-D, --data \<file\>

The YAML file which contains any other data.

Required: two arrays "in" and "out" containing tuples with before/after
values for the decoder and encoder, respectively.

You may store the scripts in this file, using "encode" and "decode"
keys.

</div>

<div class="option">

\<name\>

The name of the codec group to which this codec should be saved or
modified.

</div>

<div class="option">

\<path\>

The MoaT-KV entry to affect. Path elements '+' and '#' match exactly-one
and one-or-more subpaths. The most specific path wins.

</div>

<div class="program">

moat kv codec convert

</div>

Read, set or delete codec matches, i.e. which part of your MoaT-KV tree
is managed by which codec. To this effect, matches are tagged by a group
name.

Which codec group to apply to a given user is stored in that user's
auxiliary data as `conv=NAME`. If no such entry is present, that user's
data are not converted.

<div class="option">

-c, --codec

The codec to use on the given path. Use this option multiple times if
the codec has a multi-level name.

</div>

<div class="option">

\<name\>

The name of the codec group to which this codec should be saved or
modified.

</div>

<div class="option">

\<path\>

The MoaT-KV entry to affect. Path elements '+' and '#' match exactly-one
and one-or-more subpaths. The most specific path wins.

</div>

<div class="program">

moat kv acl

</div>

Manipulate access control lists stored in MoaT-KV.

<div class="program">

moat kv acl list

</div>

Generate a list of known ACLs.

<div class="program">

moat kv acl get

</div>

Retrieve the flags at a specific ACL path.

If the path does not contain any flags, print `-`.

<div class="option">

\<acl\>

The ACL to modify. Mandatory.

</div>

<div class="option">

\<path\>

The ACL path from which to retrieve the flags.

</div>

<div class="program">

moat kv acl set

</div>

Set the flags at a specific ACL path.

<div class="option">

-a, --acl \<MODES\>

The flag values to set. Start with `+` to add, `-` to remove modes. Use
an empty argument (`''`) to remove all rights. A lone `-` removes the
entry.

</div>

<div class="option">

\<acl\>

The ACL to modify. Mandatory.

</div>

<div class="option">

\<path\>

The ACL path to add or modify.

</div>

<div class="program">

moat kv acl test

</div>

Check whether an ACL allows access.

<div class="option">

-m, --mode \<mode\>

Check this mode (single letter). The default is "x".

</div>

<div class="option">

-a, --acl \<acl\>

In addition to the user's current ACL, also check the flag on the named
ACL.

There is no indication which of the two failed. This is intentional.

</div>

<div class="option">

\<path\>

The path to check.

</div>

<div class="program">

moat kv acl dump

</div>

Dump an ACL's content.

<div class="option">

-d, --as-dict TEXT

Print as dictionary. `TEXT` is the key used for the ACL data.

Default: Emit a list.

Using this flag requires storing the whole ACL in memory, which is
usually not a problem (unlike for data).

</div>

<div class="option">

\<name\>

The name of the ACL to dump. Mandatory.

</div>

<div class="option">

\<path\>

The path to start dumping at. Default: the root.

</div>

<div class="program">

moat kv code

</div>

Manipulate code stored in MoaT-KV.

<div class="program">

moat kv code list

</div>

List code snippets stored in MoaT-KV.

<div class="option">

-d, --as-dict \<text\>

When you use this option, the data is printed as a dictionary. The
argument of this option controls which key is used for the actual value;
this string should not occur as a path element.

The customary value to use is a single underscore.

Using this option in conjunction with `--recursive` requires keeping the
whole data set in memory before starting to print anything. This may
take a long time or eat a lot of memory.

</div>

<div class="option">

-s, --short

Print one-line entries.

Incompatible with `-f` and `-d`.

</div>

<div class="option">

-f, --full

Print the actual code.

Otherwise, code is not printed and a "number of lines" `info` entry is
generated (if missing).

</div>

<div class="option">

-m, --mindepth \<integer\>

When printing recursively, start at this depth off the given path.

The default is zero, i.e. include the entry itself.

</div>

<div class="option">

-M, --maxdepth \<integer\>

When printing recursively, stop at this depth (inclusive).

The default is to print the whole tree. Use `1` to print the entry
itself (assuming that it has a value and you didn't use `--mindepth=1`)
and its immediate children.

</div>

<div class="option">

path…

List the code below this location.

</div>

<div class="program">

moat kv code get

</div>

Retrieve Python code stored in the server.

<div class="option">

-s, --script \<filename\>

Save the code to \<filename\> instead of including it in the output.

</div>

<div class="option">

\<path\> …

Path to the code in question.

</div>

<div class="program">

moat kv code set

</div>

Store or replace Python code stored in the server.

This code will not run in the server; the purpose of these calls is to
upload code for use by client runners.

To modify some code, use `moat kv code get <path>… > <tempfile>`, edit
the tempfile, then restore with
`moat kv code set -d <tempfile> <path>…`.

<div class="option">

-d, --data \<filename\>

Load the metadata from this file.

</div>

<div class="option">

-s, --script \<filename\>

Load the code from this file.

</div>

<div class="option">

-a, --async

The code will run asynchronously, i.e. it may use `async` and `await`
statements.

You should only use the `anyio` module for sleeping, locking etc..

</div>

<div class="option">

-t, --thread

The code will run in a worker thread.

This option is incompatible with `--async`.

</div>

<div class="option">

name…

The path to the code to write.

</div>

TODO: Old versions of the code continue to run; MoaT-KV does not yet
restart users.

<div class="program">

moat kv code module

</div>

Manipulate modules stored in MoaT-KV.

Modules are replaced immediately, but code using them is **not**
auto-restarted.

This code is experimental and frankly just plain wrong: Module loading
is not deferred until "import" time. This code needs sever refactoring.
For now, please store modules in the file system.

<div class="program">

moat kv code module get

</div>

Retrieve Python module stored in the server.

<div class="option">

-s, --script \<filename\>

Save the code to \<filename\> instead of including it in the output

</div>

<div class="option">

\<path\> …

Path to the code in question.

</div>

<div class="program">

moat kv code module set

</div>

Store or replace Python code stored in the server.

This code will not run in the server; the purpose of these calls is to
upload code for use by client-side runners.

To modify a module, use `moat kv code module get <path>… > <tempfile>`,
edit the tempfile, then restore with
`moat kv code module set -d <tempfile> <path>…`.

<div class="option">

-d, --data \<filename\>

Load the metadata from this file.

</div>

<div class="option">

-s, --script \<filename\>

Load the module's code from this file.

</div>

<div class="option">

name…

The path to the code to set, below `.moat kv code proc` or whatever else
is configured under `codes`.

</div>

TODO: Old versions of the code continue to run; MoaT-KV does not yet
restart users.

<div class="program">

moat kv job

</div>

Subcommand for controlling and executing code stored in MoaT-KV.

<div class="option">

-n, --node \<node\>

The node where the code in question will run.

Code marked with this option will run on exactly this node. The default
is the local node name.

</div>

<div class="option">

-g, --group \<group\>

The group which the code in question shall run on.

The default group is "all".

</div>

<div class="program">

moat kv job run

</div>

This is the actual runner, i.e. the program that runs stored tasks.

This program does not terminate.

<div class="program">

moat kv job info

</div>

List available groups (or nodes, if `-g -` is used).

<div class="program">

moat kv job list

</div>

List available run entries.

The output is YAML-formatted unless `-t` is used.

<div class="option">

-d, --as-dict \<text\>

When you use this option, the data is printed as a dictionary. Otherwise
it's a list of dicts with the entries' path as single key.

</div>

<div class="option">

-s, --state

Add the current state.

</div>

<div class="option">

-S, --state-only

Only print the current state.

</div>

<div class="option">

-t, --table

Print a table with one line per job.

</div>

<div class="option">

\<prefix\>

Limit listing to this prefix.

</div>

<div class="program">

moat kv run get

</div>

Read a runner entry.

<div class="program">

moat kv run set

</div>

Create or change a runner entry.

<div class="option">

-c, --code \<code\>

Path to the code that this entry should execute. This value is either
split by spaces or, if `--eval` is used, interpreted as a Python
expression.

</div>

<div class="option">

-t, --time \<when\>

Time at which the runner should fire next. Seconds in the future.

</div>

<div class="option">

-r, --repeat \<seconds\>

Time after a successful execution when the runner should fire again.

</div>

<div class="option">

-d, --delay \<seconds\>

Time after an unsuccessful execution when the runner should fire again.

</div>

<div class="option">

-k, --ok \<seconds\>

If a task runs for longer than this many seconds, it's considered OK and
any error associated with it is cleared.

Errors are also cleared when a task exits, which won't work for tasks
that typically do not.

</div>

<div class="option">

-b, --backoff

Back-off exponent. The effective delay is
`delay * backoff ^ n_failures`.

To retry a failure immediately, simply use `--time now`.

</div>

<div class="program">

moat kv internal

</div>

Subcommand for viewing and modifying the internal state of a MoaT-KV
server.

<div class="program">

moat kv internal dump

</div>

This command emits MoaT-KV's internal state.

The output is comparable to `moat kv data dump -rd_`, but for internal
data.

<div class="option">

\<path\> …

Path prefix for MoaT-KV's internal data structure.

</div>

<div class="program">

moat kv internal state

</div>

This command queries the internal state of a MoaT-KV server.

All lists of `tick` values are sorted and consist of either single
entries, or `[begin,end)` tuples, i.e. the starting value is part of the
range but the end is not.

<div class="option">

-y, --yaml

Print the result of this operation as YAML data.

</div>

<div class="option">

-n, --nodes

Add a list of known nodes and their current `tick` value.

</div>

<div class="option">

-d, --deleted

Add a list of per-node deleted `tick` values, i.e. those whose entries
have been purged from the system.

</div>

<div class="option">

-p, --present

Add a list of per-node `tick` values which can be retrieved via
node+tick, i.e. for which a chain entry exists.

</div>

<div class="option">

-s, --superseded

Add a list of per-node `tick` values which have been superseded by
subsequent changes. This is returned as "known".

</div>

<div class="option">

-m, --missing

Add a list of per-node missing `tick` values, i.e. those neither in the
`known` list nor seen in any entries' chains.

</div>

<div class="option">

-r, --remote-missing

Add a list of per-node missing `tick` values that have been requested
from other servers.

</div>

See <span class="title-ref">Server protocol \<server_protocol\></span>
for details.

<div class="program">

moat kv internal mark

</div>

Mark ticks as known or deleted. This is used to clean up the `missing`
range(s) when there's a consistency problem.

<div class="option">

-d, --deleted

Add the nodes to the `deleted` list instead of the `known` list. The
effect is that if they subsequently re-surcace they'll be ignored.

</div>

<div class="option">

-b, --broadcast

Send the changes to the whole network, not just the node you're a client
of. (The local node is still targeted first, to ensure that if your
message should crash the server at least it'll only crash one.)

</div>

<div class="option">

\<node\>

The node whose ticks shall be used.

</div>

<div class="option">

\<item\> …

The tick values you want to clear. Taken from the current `missing` list
if not specified here; in this case, an empty `node` means to take the
whole list, not just the ones for `node`.

</div>

<div class="program">

moat kv internal deleter

</div>

Manage the list of nodes that collectively manage cleaning deleted
entries from the MoaT-KV tree.

All of these nodes must be online for clean-up to work.

<div class="option">

-d, --delete

Remove the mentioned nodes. Default is to add them.

</div>

<div class="option">

\<node\> …

Nodes to add or delete. If none are given, list the current state, or
(with `--delete`) clear the list, disabling node deletion.

If you want to shut deletion down temporarily, you can also add a
nonexistent node to the list.

</div>

<div class="program">

moat kv error

</div>

Manage errors.

<div class="program">

moat kv error dump

</div>

Show currently-logged errors.

<div class="program">

moat kv error resolve

</div>

Mark an error as handled.

MoaT-KV does this itself, usually, but not if the node which caused the
problem is deleted.

<div class="program">

moat kv dump

</div>

Various low-level data handling commands.

<div class="program">

moat kv dump cfg

</div>

Display the current configuration data.

<div class="program">

moat kv dump file

</div>

Unpack a file and show its contents as YAML.

<div class="option">

\<file\>

The name of the file to decode.

</div>

<div class="program">

moat kv dump init

</div>

Create an initial data file.

<div class="option">

\<node\>

The node name of the MoaT-KV server that should load the initial file.

</div>

<div class="option">

\<file\>

The file to write. Typically `/var/lib/moat/kv/%Y-%m-%d/0.dkv`.

</div>

<div class="program">

moat kv dump msg NAME…

</div>

Monitor all back-end messages. (I.e. not just those from MoaT-KV.)
Decodes MsgPack messages. Display as YAML.

<div class="option">

NAME

You may tell the monitor which stream to emit. By default it prints the
main server's update stream for data. You may use

- some random sequence of names, which is used as-is as the topic to
  monitor
- `+NAME`, to monitor this sub-stream instead
- `+` to monitor all sub-streams (recursively; does not work with the
  Serf backend)

</div>
