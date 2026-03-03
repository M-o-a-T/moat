"""
MoaT-Link to MoaT-Link gateway.

This gateway connects to a different MoaT-Link server and synchronizes data
between them. It's useful for network split recovery.
"""

from __future__ import annotations

import anyio

from moat.link.client import Link
from moat.link.meta import MsgMeta

from . import DelayedGate, GateNode

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.lib.path import Path


# Paths that should not be synced between servers
SKIP_PATHS = frozenset(["run"])


class Gate(DelayedGate):
    """
    A gateway that connects to another MoaT-Link server.

    Configuration:
        src: Path - source path to synchronize (in local MoaT-Link)
        server: str - name of the remote server to connect to
        delay: float - delay in seconds (default 0.1)
        skip: list[str] - additional path prefixes to skip (default: ["run"])

    The gateway monitors the same path on the remote server and synchronizes
    changes bidirectionally, using the DelayedGate delay mechanism to handle
    conflicts where the same data is updated on both sides.

    Note: The "run" subpath is always skipped as it contains operational
    data (client IDs, ping status, etc.) that should not be synchronized.
    """

    _remote_link: Link
    _remote: Any  # LinkSender
    _skip_paths: frozenset

    def __init__(self, cfg, cf, path, link):
        super().__init__(cfg, cf, path, link)
        # Build the set of paths to skip
        extra_skip = cf.get("skip", [])
        self._skip_paths = SKIP_PATHS | frozenset(extra_skip)

    def _should_skip(self, path: Path) -> bool:
        """
        Check if a path should be skipped (not synced).
        """
        if not path:
            return False
        return path[0] in self._skip_paths

    async def run_(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Run the gateway with a connection to the remote server.
        """
        server_name = self.cf.get("server")
        if not server_name:
            raise ValueError("Link gate requires 'server' configuration")

        # Connect to the remote server
        async with Link(self.link.link.cfg, only=server_name) as remote:
            self._remote = remote
            await super().run_(task_status=task_status)

    async def get_dst(self, *, task_status=anyio.TASK_STATUS_IGNORED):
        """
        Monitor data from the remote server.
        """
        async with self._remote.d_watch(
            self.cf.src, subtree=True, state=None, meta=True, mark=True
        ) as mon:
            task_status.started()
            async for pdm in mon:
                if pdm is None:
                    self.dst_is_current()
                    continue
                p, d, m = pdm
                # Skip operational paths
                if self._should_skip(p):
                    continue
                if m is not None and m.origin == self.origin:
                    # This is our own update echoed back, skip it
                    continue
                await self.set_src(p, d, m)

    async def _set_dst(self, path: Path, node: GateNode, data: Any, meta: MsgMeta):
        """
        Queue an update to the remote server, with filtering.
        """
        # Skip operational paths
        if self._should_skip(path):
            return
        await super()._set_dst(path, node, data, meta)

    async def set_dst(self, path: Path, data: Any, meta: MsgMeta, node: GateNode):
        """
        Send data to the remote server.
        """
        remote_meta = MsgMeta(origin=self.origin, timestamp=meta.timestamp)
        await self._remote.d_set(self.cf.src + path, data, remote_meta)
        node.ext_meta = remote_meta

    def is_update(self, node: GateNode, data: Any, meta: MsgMeta):  # noqa: ARG002
        """
        Test whether this is an update from the remote.
        """
        # If the metadata match, it's not an update
        try:
            if node.ext_meta.origin == meta.origin and node.ext_meta.timestamp == meta.timestamp:
                return False
        except (AttributeError, KeyError):
            pass
        return True

    def newer_dst(self, node: GateNode):
        """
        Check whether the remote data is newer.

        This is called at startup when both sides have data.
        """
        # If the remote has no metadata, assume it's newer (shouldn't happen)
        if not node.ext_meta:
            return True

        # If the local message is from us, the remote is newer
        if self.origin == node.meta.origin:
            return True

        # If the remote message is from us, the local is newer
        if self.origin == node.ext_meta.origin:
            return False

        # If the local has a copy of the remote metadata, check if data matches
        if "gw" in node.meta:
            if node.meta["gw"] == node.ext_meta:
                return None if node.data_ == node.ext_data else True
            else:
                return True

        # If timestamps are too close, can't decide
        if abs(node.ext_meta.timestamp - node.meta.timestamp) < 0.1:
            return None

        # Use the message with the newer timestamp
        return node.ext_meta.timestamp > node.meta.timestamp
