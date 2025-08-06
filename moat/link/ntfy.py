from __future__ import annotations

import anyio
import httpx
import time
from moat.link import protocol_version
from moat.util.misc import srepr

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import NoReturn
    c3
    from moat.link.client import Link

__all__ = ["ntfy_bridge"]

async def keepalive(link:Link, http:httpx.AsyncClient, keep:dict, cfg:dict) -> NoReturn:
    keep = dict(**keep)
    path = keep.pop("path")
    timeout = keep.pop("timeout")
    try:
        topic = keep.pop("topic")
    except KeyError:
        try:
            topic = cfg.get("topic")
        except KeyError:
            raise click.UsageError("In config link.notify, either 'keepalive' or 'ntfy' needs a 'topic'.") from None
    message = keep.pop("message")
    async with link.d_watch(path) as mon:
        it = aiter(mon)
        while True:
            with anyio.move_on_after(timeout):
                await anext(it)
                continue

            # owch
            url = cfg["url"].replace("{TOPIC}",topic)
            await http.post(cfg["url"]+f"/{topic}", data=message, headers=keep)
            await anext(it)


prio_map = {
    "debug":1,
    "info":2,
    "warning":3,
    "error":4,
    "fatal":5,
}

async def ntfy_bridge(link:Link, keep:dict, cfg:dict) -> NoReturn:
    """
    A bridge that monitors the Notify subchannel and forwards to NTFY.SH
    (or a private server).
    """
    async with (
        anyio.create_task_group() as tg,
        httpx.AsyncClient() as http,
    ):
        tg.start_soon(keepalive, link,http,keep,cfg)

        async with link.d_watch(cfg["path"],subtree=True,meta=True,state=None) as mon:
            async for path,msg,meta in mon:
                t = time.time()
                if meta.timestamp < t-cfg["max_age"]:
                    continue
                await ntfy_send(http,cfg,path,msg)


async def ntfy_send(http,cfg,path,msg):
    try:
        topic = cfg["topic"]
    except KeyError:
        try:
            topic = path[0]
        except IndexError:
            topic = "TOP"
    url = cfg["url"]+"/"+topic
    tags = [str(path)]
    if isinstance(msg,dict):
        msg = dict(**msg)
        hdr = {}
        data = msg.pop("msg","")
        tags.extend(msg.pop("tags",()))

        if "title" in msg:
            hdr["title"] = msg.pop("title")
        if "prio" in msg:
            try:
                prio = sg.pop("prio")
                hdr["prio"] = prio_map[prio]
                if hdr["prio"] > 3:
                    tags.append("warning")
            except KeyError:
                hdr["prio"] = "high"
                data = f" (prio:{prio})"
        if msg:
            data += " "+srepr(msg)

    else:
        data = str(msg)
        hdr = {"title":"MoaT"}

    hdr["tags"] = ",".join(str(x) for x in tags)
    if msg and not data:
        data = str(msg)
    await http.post(url, data=data, headers=hdr)
