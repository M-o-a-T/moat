(moat-common)=
# Project Information

## History

The MoaT started as a personal project for resilient home automation
(i.e. no master server, resilient in the face of network partitions,
strong data typing, etc.) but sprawled off from that.

The current focus is on feature completeness, documentation, test coverage,
and adding typing that pyright is happy about.

## Opinions and Standards

The MoaT is admittedly a somewhat opinionated codebase.
The plus side is that we don't need to think about which mechanism to select
when a single one is used pretty much everywhere.

### [Paths](path.md)

A file system path uses slashes and can only understand strings.

MoaT uses dots (and colons); it may contain numbers, other basic types, and
even tuples.

### Configuration

Python programmers have a love-hate relationship with dictionaries whose
elements can be addressed with dot syntax. The MoaT is no exception.

Most of the code base uses a simple dict with additional `__getattr__` and
`__setattr__` methods that simply translate to `__getitem__` and friends.

We're going to move away from that.

### Data Serialization

We like CBOR. Yes it has its faults but it's regular, self-describing,
and self-delimiting. (It also it supports stream data, i.e. data types
with no pre-determined length, but MoaT currently doesn't use that feature.)

We like YAML, much for the same reasons.

There is no TOML or JSON in the MoaT codebase, other than `pyproject.toml`
of course. Anything that wants JSON will require a translator.

See [CBOR](cbor.md) for MoaT's conventions and additions.

:::{admonition} Why not MsgPack?
:class:note

- MsgPack's extensions are binary strings, not objects.

- Due to its regular structure, a CBOR codec is actually smaller than its
  MsgPack cousin.

- CBOR has a rich set of commonly-used extensions.
:::



### Discoverability

There is one command. It's called `moat`. Everything else is done with
subcommands (and sub-subcommands and …). `--help` is your friend.

```{toctree}
:maxdepth: 2
:hidden:

CONDUCT
HACKING
DOC
cbor
path
```
