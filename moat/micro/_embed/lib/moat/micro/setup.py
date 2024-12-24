"""
MoaT Python setup

Side effects only. Just import this.
"""

from __future__ import annotations

from micropython import alloc_emergency_exception_buf

alloc_emergency_exception_buf(300)
