(moat-lib-rpc)=
# RPC: Remote Procedure Calls

```{include} ../../packaging/moat-lib-rpc/README.md
:start-after: % start main
:end-before: % end main
```

## Manual

### Setup

There are several ways to initiate a MoaT-RPC connection.

Each of them is an async context manager that yields a
{class}`~moat.lib.rpc.MsgSender` object (or a subclass).

#### MoaT-RPC

TODO.

#### MoaT-Link

See the {py:class}`moat.link.client.Link` class. Besides standard client
methods, you can use the {py:meth}`~moat.link.client.LinkSender.get_service`
method to talk to other clients that registered themselves via an
{py:meth}`~moat.link.client.LinkSender.announcing` context (assuming that they
offer some service under that name).


#### MoaT-RPC

You enter a {class}`~moat.lib.rpc.RootCmd` context. The command structure
is described in the configuration you pass to it. Typically you then pass
a configurable path to {meth}`~moat.lib.rpc.MsgSender.sub_at`.


#### TODO



### Sending commands

MoaT commands are by design

* asynchronous
* hierarchical
* streaming-aware (sometimes)

The main entry point is a {class}`~moat.lib.rpc.MsgSender`.
You can call {meth}`~moat.lib.rpc.MsgSender.sub_at` to access (part of) the
path to your destination, then use chained attributes and an async function
call to access the destination. Alternately, you can use an async context
manager to set up a data stream.

```python
async with SomeRPC() as rpc:
    async with pc.sub_at(P("foo")) as foo:
        answer = await foo.bar("Arthur")
        assert answer == 42
        async with foo.baz.quux(10) as msg:
            assert msg[0] == 0
            async for m in msg:
                print("Quux:", m.args[0])
        assert msg[0] == 55
```

### Handling commands

The Streams library provides the foundational {class}`~moat.lib.stream.Base`
class. Its main entry point is its async context, which

* sets up an exit stack
* calls {meth}`~moat.lib.stream.Base.setup` before,
  and {meth}`~moat.lib.stream.Base.teardown` after, yielding

On top of that, {class}`~moat.lib.rpc.MsgHandler`

* takes part in the message handler hierarchy, i.e. has a `root` pointer
* has a `handle` method that handles basic messages (`dir_`, `rdy_`, `doc_`)
* includes a sub-command accessor that can be overridden

Next, {py:class}`moat.lib.rpc.cmd._base.BaseCmd`

* has a background task (the `task` method)
* carries event for starting/started/stopped
* encapsulates the objects's context and its task via the `run` method

#### Incoming commands

The command handler directs incoming commands to `cmd_NAME` or `stream_NAME` methods.

`cmd_NAME` is only called when streaming is not used. Its signature is
effectively exported to the caller:

```python
class Foo(BaseCmd):
    async def cmd_bar(self, name):
        print(f"Hello, {name}!")
        return 42
```

`stream_NAME` methods get a single {class}`~moat.lib.rpc.Msg` argument that
encapsulates the caller's. They can be called without streaming if there is
no `cmd_NAME` method.

```python
class Baz(BaseCmd):
    async def stream_quux(self, msg:Msg):
        if msg.can_stream:
            n = msg[0]
            async with msg.stream_out(0) as ms:
                for n in range(1,n+1):
                    await ms.send(n)
                await ms.result(n*(n+1)/2)  # sum ;-)
        else:
            print(f"Wanted: {msg[0]} quux.")
```

Also, by default `sub_NAME` methods are called when the path isn't
finished. Typically this is a sub-{py:class}`~moat.lib.rpc.cmd._base.BaseCmd`,
in which case its {py:meth}`~moat.lib.rpc.MsgHandler.handle` method will be
called:

```python
class Foo(BaseCmd):
    async def setup(self):
        await super().setup()
        self.sub_baz = AC_use(self, Baz(cfg.baz))
```

#### Root command handler

The root is typically a {py:class}`moat.lib.rpc.cmd.base.RootCmd`. It does *not*
inherit from {py:class}`~moat.lib.rpc.cmd._base.BaseCmd`, or even
{py:class}`~moat.lib.rpc.MsgHandler`, because it delegates (almost) everything
to its subordinate app. Instead, when you enter its context it

* starts its subordinate app
* starts its `task` method, if present
* contains a built-in {py:class}`~moat.lib.rpc.MsgSender` for referring
  directly to subcommands (if possible)


```{toctree}
:maxdepth: 2
:hidden:

messages
api
```
