"""
Link RTC backend.

Provides remote access to RTC data via the root command handler.
"""

from __future__ import annotations

from . import RTC as _RTC
from . import NotSync, RTCBase

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class RTC(RTCBase):
    """
    Link RTC backend.

    Provides remote access to RTC data via self.root.sub_at(self.cfg["path"]).
    This backend is asynchronous and cannot be used in synchronous contexts.

    The backend is expected to be callable with zero to two arguments::

    - *No argument*: return a list of available names.
    - name(str): return the data stored under that name.
    - name(str), `NotGiven`: delete the data stored under that name.
    - name(str), data(Any): store the data under that name.
    """

    is_FS = False
    is_ASYNC = True

    def __init__(self, cfg):
        super().__init__(cfg)
        self._path = cfg.get("path", ("rtc",))
        if isinstance(self._path, str):
            self._path = tuple(self._path.split("."))

    def _get_sender(self):
        """Get the SubMsgSender for our path."""
        root = _RTC.root
        if root is None:
            raise NotSync("No root connection")
        return root.sub_at(self._path)

    def reload(self):
        """Reload is a no-op for the link backend."""
        pass

    async def get(self, name: str) -> Any:
        """
        Get a value from the remote RTC.

        Args:
            name: The key to retrieve.
            all: Unused, for API compatibility.

        Returns:
            The stored value.

        Raises:
            KeyError: If the key doesn't exist.
            NotSync: If no root connection is available.
        """
        sender = self._get_sender()
        try:
            return await sender(name)
        except KeyError:
            raise
        except Exception as exc:
            raise KeyError(name) from exc

    async def set(self, name: str, data: Any) -> bool:
        """
        Set a value in the remote RTC.

        Args:
            name: The key to store.
            data: The value to store. `NotGiven` deletes.

        Returns:
            True if the value was written.

        Raises:
            NotSync: If no root connection is available.
        """
        sender = self._get_sender()
        await sender(name, data)
        return True

    async def keys(self) -> set[str]:
        """
        Get all stored data from the remote.

        Returns:
            A set of all stored values.

        Raises:
            NotSync: If no root connection is available.
        """
        sender = self._get_sender()
        return set(await sender())
