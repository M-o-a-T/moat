"""
This module forwards notifications to NTFY.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import httpx

from moat.util import P, Path

from . import Notifier as BaseNotifier

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Sequence

__all__ = ["Notifier"]

prio_map = {
    "debug": 1,
    "info": 2,
    "warning": 3,
    "error": 4,
    "fatal": 5,
}


class Notifier(BaseNotifier):  # noqa:D101
    @asynccontextmanager
    async def _ctx(self):
        async with (
            super()._ctx(),
            httpx.AsyncClient() as self.http,
        ):
            yield self

    async def send(
        self,
        topic: str | Path,
        title: str,
        msg: str,
        prio: str | None = None,
        tags: Sequence[str] = (),
        **kw,  # noqa: ARG002
    ):
        "Forward a message to NTFY"

        if "topic" in self.cfg:
            top = self.cfg.topic
        else:
            if isinstance(topic, str):
                topic = P(topic)
            try:
                top = topic[0]
            except IndexError:
                top = "TOP"
            else:
                topic = Path.build(topic[1:])

        url = self.cfg.url + "/" + top
        tags = list(tags)
        tags.append(str(topic))

        hdr = {}

        if title:
            hdr["title"] = title
        if prio is not None:
            try:
                prio = prio_map[prio]
                hdr["prio"] = str(prio)
                if prio > 3:
                    tags.append("warning")
            except KeyError:
                hdr["prio"] = "high"
                msg += f" (prio:{prio})"
        hdr["tags"] = ",".join(str(x) for x in tags)

        if "token" in self.cfg:
            hdr["authorization"] = f"Bearer {self.cfg['token']}"

        await self.http.post(url, data=msg, headers=hdr)
