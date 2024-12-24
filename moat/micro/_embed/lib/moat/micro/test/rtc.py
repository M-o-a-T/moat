"""
Fake RTC, actually writes he state to disk

Linux only
"""

from __future__ import annotations

import moat.micro._rtc as _rtc


class _FakeRTC:
    FN = "fake.rtc"

    def __init__(self):
        try:
            with open(self.FN, "rb") as f:
                self._m = f.read()
        except OSError:  # file not found
            self._m = b""

    def memory(self, data=None):
        if data is None:
            return self._m
        else:
            self._m = data
            with open(self.FN, "wb") as f:
                f.write(data)


_rtc.RTC = _FakeRTC
state = _rtc.State()
