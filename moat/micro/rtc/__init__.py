"""
Main interface to the real-time clock
"""

from __future__ import annotations

from moat.util import NotGiven, de_async, merge
from moat.lib.micro import log

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from moat.lib.rpc import RootCmd

    from collections.abc import Awaitable
    from typing import Any, ClassVar


class NotSync(RuntimeError):
    """
    This RTC implementation can't access its data synchronously.
    """


class _RTC:
    """
    Singleton class for RTC access

    Config:
        back: list of backend names to use

    """

    backends: list[RTCBase]
    root = None

    def __repr__(self):
        return "<RTC>"

    def init(self, cfg: dict | None = None):
        self.cfg = cfg or {"use": ["mem", "fs"]}
        self._be = {}
        self._setup()

        try:
            cfg = de_async(self.get, "rtc", sync=True)
        except KeyError:
            pass
        except Exception as exc:
            log("No RTC config: %r", exc)
        else:
            merge(self.cfg, cfg)
            self._setup()

    def set_root(self, root: RootCmd):
        self.root = root
        self._setup()

    def _setup(self, err: bool = False):
        self.backends = bes = []
        nbe = set(self._be.keys())
        mp = "moat.micro.rtc."  # module name prefix

        for i, c in enumerate(self.cfg.get("use", [])):
            if isinstance(c, str):
                c = {"name": c}  # noqa:PLW2901
            n = c.get("name", str(i))
            if (be := self._be.get(n, None)) is not None:
                be.reload()
            else:
                try:
                    m = c.get("mod", n)
                    if "." not in m:
                        m = mp + m

                    cls = __import__(m, globals(), None, ("RTC",), 0).RTC
                    be = cls(c)  # RTCBase instance
                    if be.is_ASYNC is False:
                        be.is_ASYNC = None
                    elif be.is_ASYNC is None:
                        be.is_ASYNC = True
                        self._be[n] = be
                        bes.append(be)
                        nbe.discard(n)
                        be = cls(c)  # RTCBase instance
                        be.is_ASYNC = False
                        n += "_sync"
                        be.cfg["name"] = n

                except Exception as exc:
                    if err:
                        raise
                    if not isinstance(exc, ImportError) or m != mp + "mem":
                        log("RTC error for %s", n, err=exc)
                    continue
            self._be[n] = be
            bes.append(be)
            nbe.discard(n)
        for n in nbe:
            be = self._be.pop(n)

    def reload(self):
        self._setup(err=True)

    def state(self, name: str) -> State:
        """
        State accessor.
        """
        return State(self, name)

    def get_sync(self, name, fs=None, default=NotGiven):
        """
        Synchronous getter for RTC data.

        Args:
            name: The key to retrieve.
            fs: Access the file system?
            default: Default value if key not found.

        Returns:
            The stored value, or default if not found.

        Raises:
            KeyError: If key not found and no default provided.
        """
        try:
            return de_async(self.get, name, fs=fs, sync=True)
        except KeyError:
            if default is NotGiven:
                raise
            return default

    def set_sync(self, name: str, value: Any, **kw):
        """
        Synchronous setter for RTC data.

        Args:
            name: The key to store.
            value: The value to store.

        Other keyword args are forwarded to :meth:`set`.
        """
        de_async(self.set, name, value, sync=True, **kw)

    async def get(self, name: str, fs: bool | None = None, sync: bool = False) -> Any:
        """
        Retrieve an RTC datum.

        Args:
            name: The data to get.
            fs: Access the file system?
            sync: if set, this call must not yield.
        """
        exc = None
        exc2 = None

        for be in self.backends:
            if fs is (not be.is_FS):
                continue
            if be.is_ASYNC is sync:
                continue
            try:
                res = await be.get(name)
                return res
            except KeyError:
                pass
            except NotSync:
                exc2 = NotSync(name)
            except Exception as err:
                exc = err
        if exc is not None:
            raise exc from None
        if exc2 is not None:
            raise exc2 from None
        raise KeyError(name) from None

    async def keys(self, fs: bool | None = None, sync: bool = False) -> set[str]:
        """
        Get the list of available/existing RTC keys.
        """
        res = set()

        for be in self.backends:
            if fs is (not be.is_FS):
                continue
            if be.is_ASYNC is sync:
                continue
            res.update(await be.keys())

        return res

    async def set(
        self,
        name: str,
        data: Any,
        fs: bool | None = None,
        sync: bool = False,
        all: bool | None = True,  # noqa:A002
    ) -> None:
        """
        Set an RTC datum.

        Args:
            name: The data to get.
            data: The data to write.
            fs: Access the file system?
            sync: Flag whether yielding is blocked.
            all: Write to all backends?

            *all* can be
            - `True`: write to all backends.
            - `False`: only use the first available backend.
            - `None`: write to the first matching backend. Erase this key
              from other backends.
        """
        seen = False
        exc = None
        if fs is None and all is None:
            try:
                await self.set(name, data, fs=False)
            except NotImplementedError:
                pass
            await self.set(name, data, fs=True)
            return

        for be in self.backends:
            if be.is_ASYNC is sync:
                continue
            try:
                if fs is (not be.is_FS):
                    continue
                if not await be.set(name, data):
                    continue
                seen = True

                if all is None:
                    data = NotGiven
                elif not all:
                    return
            except KeyError:
                continue
            except Exception as err:
                exc = err
        if exc is not None:
            raise exc from None
        if not seen:
            raise NotImplementedError(name)


RTC = _RTC()


class State:
    """
    Accessor for a single state.
    """

    def __init__(self, rtc: RTCBase | _RTC, name: str, fs: bool | None = None):
        self.rtc = rtc
        self.name = name
        self.fs = fs

    def get(self, **kw) -> Awaitable[Any]:
        "Getter."
        if "fs" not in kw:
            kw["fs"] = self.fs
        return self.rtc.get(self.name, **kw)

    def set(self, data: Any, **kw) -> Awaitable[None]:
        "Setter."
        if "fs" not in kw:
            kw["fs"] = self.fs
        return self.rtc.set(self.name, data, **kw)


class RTCBase:
    """
    Base class for RTC backends.

    Class variables:
        is_FS: This class accesses a (Flash) file system, thus should not be
               write often (if at all).
        is_ASYNC: Flag whether the implementation yields, i.e. cannot
                  be called synchronously.
                  If `None`, the loader shall create both a
                  sync and an async version.
    """

    is_FS: ClassVar[bool] = False
    is_ASYNC: bool | None = None

    def __init__(self, cfg):
        self.cfg = cfg
        sync = cfg.get("sync", None)
        if self.is_ASYNC is None:
            self.is_ASYNC = sync
        elif sync is (not self.is_ASYNC):
            raise ValueError("Sync settings don't match")

    def __repr__(self):
        return f"<{self._name}>"

    @property
    def _name(self):
        try:
            return self.cfg["name"]
        except KeyError:
            try:
                return self.cfg["mod"]
            except KeyError:
                return self.__class__.__name__

    async def get(self, name: str) -> Any:
        """
        Getter.
        """
        raise NotImplementedError

    async def set(self, name: str, data: Any) -> bool:
        """
        Setter.

        Returns:
            True if it could write.
        """
        raise NotImplementedError

    def state(self, name: str) -> State:
        """
        State accessor for a specific RTC.
        """
        return State(self, name)

    async def keys(self) -> set[str]:
        """
        Get all available keys.
        """
        raise NotImplementedError


def at(*a, **kw):
    """
    Setter for debugging.

    Usage: call ``at("something", or_other=42)`` at various places in your
    code. After a crash the data from the last such call will be available
    by calling ``RTC.get_sync("debug")``.
    """
    try:
        if (RTC.get_sync("state") + ",").startswith("safe,"):
            return
    except KeyError:
        pass
    data = (a, kw) if a and kw else (a or kw)
    try:
        RTC.set_sync("debug", data, fs=False)
    except NotImplementedError:
        pass
