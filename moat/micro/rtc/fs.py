"""
File system RTC backend.

Stores data in a CBOR file on the file system.
Supports direct file mapping for specific keys.
"""

from __future__ import annotations

from moat.util import NotGiven
from moat.lib.codec.cbor import CBOR_TAG_CBOR_FILEHEADER, Tag
from moat.lib.codec.moat_cbor import Codec as CBOR
from moat.lib.micro import log

from . import RTCBase

_codec = CBOR()


class RTC(RTCBase):
    """
    File system RTC backend.

    Stores data in a CBOR file at cfg["dest"] (default: "moat.data").
    Supports direct file mapping via cfg["direct"] (key→filename dict):
    values for these keys must be strings and are written directly to files.

    Class variables:
        is_FS: True - this uses the file system
        is_SYNC: None - configurable via cfg["sync"]
    """

    is_FS = True
    is_SYNC = None  # configurable

    def __init__(self, cfg):
        super().__init__(cfg)
        self._d = {}
        self._dest = cfg.get("dest", "moat.data")
        self._direct = cfg.get("direct", {"state": "moat.state"})
        self._load()

    def _load(self):
        """Load data from the state file."""
        try:
            with open(self._dest, "rb") as f:
                data = f.read()
            if data:
                decoded = _codec.decode(data)
                if isinstance(decoded, Tag) and decoded.tag == CBOR_TAG_CBOR_FILEHEADER:
                    self._d = decoded.value
                elif isinstance(decoded, dict):
                    self._d = decoded
        except OSError:
            # File doesn't exist yet
            self._d = {}
        except Exception as exc:
            log("RTC fs load error", err=exc)
            self._d = {}

    def _save(self):
        """Save data to the state file."""
        tagged = Tag(CBOR_TAG_CBOR_FILEHEADER, self._d)
        with open(self._dest, "wb") as f:
            f.write(_codec.encode(tagged))

    def _get_direct(self, name: str):
        """Get a value from a direct file."""
        fn = self._direct[name]
        try:
            with open(fn, "r") as f:
                return f.read()
        except OSError:
            raise KeyError(name) from None

    def _set_direct(self, name: str, data: str) -> bool:
        """Set a value in a direct file."""
        fn = self._direct[name]
        with open(fn, "w") as f:
            f.write(data)
        return True

    def _del_direct(self, name: str) -> bool:
        """Delete a direct file."""
        fn = self._direct[name]
        try:
            import os  # noqa:PLC0415

            os.remove(fn)
        except OSError:
            pass
        return True

    def reload(self):
        """Reload data from the state file."""
        self._load()

    async def get(self, name: str):
        """
        Get a value from the file system.

        Args:
            name: The key to retrieve.
            all: Unused, for API compatibility.

        Returns:
            The stored value.

        Raises:
            KeyError: If the key doesn't exist.
        """
        # Check direct files first
        if name in self._direct:
            return self._get_direct(name)

        if name not in self._d:
            raise KeyError(name)
        return self._d[name]

    async def set(self, name: str, data) -> bool:
        """
        Set a value in the file system.

        Args:
            name: The key to store.
            data: The value to store.

        Returns:
            True if the value was written.
        """
        # Handle direct files
        if name in self._direct:
            if data is NotGiven:
                return self._del_direct(name)
            if not isinstance(data, str):
                raise TypeError(f"Direct file {name} requires string value")
            try:
                if self._get_direct(name) == data:
                    return True
            except KeyError:
                pass
            return self._set_direct(name, data)

        if data is NotGiven:
            if name not in self._d:
                return True
            del self._d[name]
        else:
            self._d[name] = data
        self._save()
        return True

    async def all(self):
        """
        Get all stored data.

        Returns:
            A copy of the internal data dict (does not include direct files).
        """
        return dict(self._d)
