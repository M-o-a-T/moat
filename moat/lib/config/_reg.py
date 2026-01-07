"""
Configuration registration for deferred processing.
"""

from __future__ import annotations

# Set of configuration names to process
to_process: set[str] = set()


def register(name: str) -> None:
    """
    Register a configuration name for deferred processing.

    This allows configuration to be registered during module initialization
    without triggering circular dependencies.

    Args:
        name: Configuration name to register
    """
    to_process.add(name)
