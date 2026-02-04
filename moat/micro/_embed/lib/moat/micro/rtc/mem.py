"""
RTC memory backend.

Uses the hardware RTC memory for fast, synchronous access.
Data is stored as a CBOR-encoded dict tagged with CBOR_TAG_CBOR_FILEHEADER.
"""

from __future__ import annotations

from moat.util import NotGiven
from moat.lib.codec.cbor import CBOR_TAG_CBOR_FILEHEADER, Tag
from moat.lib.codec.moat_cbor import Codec as CBOR
from moat.lib.micro import log

from . import RTCBase

try:
    from machine import RTC as _RTC
except ImportError:
    _RTC = None

_codec = CBOR()


class RTC(RTCBase):
    """
    RTC memory backend.

    Uses machine.RTC().memory for hardware access.
    Data is stored as a CBOR-encoded dict tagged with CBOR_TAG_CBOR_FILEHEADER.
    Loads on init, saves on every write.
    """

    is_FS = False
    is_ASYNC = False

    def __init__(self, cfg):
        super().__init__(cfg)
        self._d = {}
        self._mem = None

        if _RTC is None:
            raise ImportError("No machine.RTC available")

        try:
            r = _RTC()
            self._mem = r.memory
        except (TypeError, AttributeError) as exc:
            raise ImportError("RTC memory not available") from exc

        self._load()

    def _load(self):
        """Load data from RTC memory."""
        if self._mem is None:
            return

        try:
            data = self._mem()
            if data and data[0:3] == b"\xd9\xd9\xf7":
                decoded = _codec.decode(data)
                if isinstance(decoded, Tag) and decoded.tag == CBOR_TAG_CBOR_FILEHEADER:
                    self._d = decoded.value
                elif isinstance(decoded, dict):
                    self._d = decoded
        except Exception as exc:
            log("RTC mem load error", err=exc)
            self._d = {}

    def _save(self):
        """Save data to RTC memory."""
        if self._mem is None:
            return
        tagged = Tag(CBOR_TAG_CBOR_FILEHEADER, self._d)
        self._mem(_codec.encode(tagged))

    def reload(self):
        """Reload data from RTC memory."""
        self._load()

    async def get(self, name: str):
        """
        Get a value from RTC memory.

        Args:
            name: The key to retrieve.
            all: Unused, for API compatibility.

        Returns:
            The stored value.

        Raises:
            KeyError: If the key doesn't exist.
        """
        if name not in self._d:
            raise KeyError(name)
        return self._d[name]

    async def set(self, name: str, data) -> bool:
        """
        Set a value in RTC memory.

        Args:
            name: The key to store.
            data: The value to store (must be CBOR-encodable).

        Returns:
            True if the value was written.
        """
        if data is NotGiven:
            if name in self._d:
                del self._d[name]
                self._save()
            return True

        self._d[name] = data
        self._save()
        return True

    async def keys(self):
        """
        Get keys for all stored data.

        Returns:
            A set of names.
        """
        return set(self._d.keys())
