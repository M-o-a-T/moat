class CtxObj:
    """
    Add an async context manager that calls `_ctx` to run the context.

    Usage::
        class Foo(CtxObj):
            @asynccontextmanager
            async def _ctx(self):
                yield self # or whatever

        async with Foo() as self_or_whatever:
            pass
    """

    async def __aenter__(self):
        self.__ctx = ctx = self._ctx()  # pylint: disable=E1101,W0201
        return await ctx.__aenter__()

    def __aexit__(self, *tb):
        return self.__ctx.__aexit__(*tb)
