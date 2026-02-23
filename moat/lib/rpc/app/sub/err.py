"""
Error handler and retry app.
"""

from __future__ import annotations

from moat.lib.rpc import RetryCmd


class Err(RetryCmd):
    """An error handler and possibly-retrying subcommand manager."""

    pass
