# Data Model

This section documents some of MoaT-KV's server-internal classes.

<div class="automodule" members="">

moat.kv.model

</div>

## ACLs

ACL checks are performed by `~moat.kv.types.ACLFinder`. This class
collects all relevant ACL entries for any given (sub)path, sorted by
depth-first specificty. This basically means that you collect all ACLs
that could possibly match a path and sort them; the `+` and `#`
wildcards get sorted last. Then the system picks the first entry that
actually has a value.

This basically means that if you have a path `a b c d e f g` and ACLs
`a b # g` and `a # d e f g`, the first ACL will match because `b` is
more specific than `#`, even though the second ACL is longer and thus
could be regarded as being more specific. However, the current rule is
more stable when used with complex ACLs and thus more secure.

<div class="autoclass" members="">

moat.kv.types.ACLFinder

</div>

## Helper methods and classes

<div class="autoclass" members="">

moat.kv.util.MsgWriter

</div>

<div class="automodule" members="">

moat.kv.util

</div>

> This object marks the absence of information where simply not using
> the data element or keyword at all would be inconvenient.
>
> For instance, in `def fn(value=NotGiven, **kw)` you'd need to test
> `'value'  in kw`, or use an exception. The problem is that this would
> not show up in the function's signature.
>
> With `NotGiven` you can simply test `value is` (or `is not`)
> `NotGiven`.

<div class="automodule" members="">

moat.kv.runner

</div>

<div class="automodule" members="">

moat.kv.actor

</div>
