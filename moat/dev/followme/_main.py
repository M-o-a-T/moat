#!/usr/bin/env python3
"""
followmeprint_dl.py — Talk to the Y Soft SafeQ "Rubicon" web client
                       (Follow-Me-Print) at
                       https://followmeprint.office.noris.de/webclient/#/download

The page is an Angular SPA backed by several micro-services.  Instead of
driving a browser we replicate the SPA's own REST calls:

  * discover backend  : HEAD {origin}/webclient/  ->  `WebConfigUrl` header
                        GET  {WebConfigUrl}/web-config  ->  service URL map
  * login             : POST {authenticationServiceUrl}/auth-user
                            {"AuthMode":"Credentials","Username":..,
                             "Password":..,"PinCode":"","Mandator":""}
                        -> JWT (JSON-quoted string), valid ~7 days
  * refresh           : POST {authenticationServiceUrl}/jwt/refresh
                          (Bearer)  -> new JWT, exp = now + 7 days
  * list scans        : GET  {imageServiceUrl}/webclient-get-files
                        -> [{Guid, FileName, FileSizeBytes, Date, PageCount}]
  * download one      : GET  {imageServiceUrl}/webclient-download-file/{Guid}
  * delete one        : POST {imageServiceUrl}/webclient-delete-files
                              ["<Guid>"]

Subcommands
-----------
    login      Authenticate, print the JWT and how long it stays valid.
               Writes the token to a file (disable with --no-save) so the
               other commands can reuse it.  If PASSWORD is absent from the
               CREDS file it is read from stdin (tty -> hidden prompt).
    fetch      List the documents on the #/download page.
               Optionally download and/or delete each one.
    poll       Repeat `fetch` every N seconds (handy to grab scans as they
               arrive).  Honours the same --download/--delete flags.
               With --notify, MoaT-Link notifications are sent below the
               "notify.scan" topic: one at "notify.scan.poll" when polling
               starts, and one per downloaded document (or a summary;
               see --notify-mode).
    refresh    Exchange the current (still-valid) token for a freshly minted
               one, resetting the 7-day clock.

Built with anyio + httpx + asyncclick.
"""

from __future__ import annotations

import anyio
import base64
import getpass
import json
import os
import re
import sys
import time
from anyio.to_thread import run_sync
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import asyncclick as click
import httpx

from moat.lib.config import CFG
from moat.lib.path import P

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.link.client import LinkSender

    from collections.abc import AsyncIterator


# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #
DEFAULT_PAGE_URL = "https://followmeprint.office.noris.de/webclient/#/download"
DEFAULT_CREDS = "./CREDS"
JWT_ENV = "FMP_TOKEN"
TIMEOUT = 60.0  # seconds; scanned PDFs can be tens of MB
CHUNK = 64 * 1024

CREDS_RE = re.compile(r'^\s*(USER|PASS)\s*=\s*(?:"([^"]*)"|\'([^\']*)\'|(.*?))\s*$', re.IGNORECASE)


def _default_token_file() -> str:
    """Token cache location: $XDG_CACHE_HOME/followmeprint/token (or ~/.cache/...)."""
    base = os.environ.get("XDG_CACHE_HOME") or os.path.expanduser("~/.cache")
    return str(Path(base) / "followmeprint" / "token")


# --------------------------------------------------------------------------- #
# Small utilities
# --------------------------------------------------------------------------- #
def origin_of(page_url: str) -> str:
    sp = urlsplit(page_url)
    return urlunsplit((sp.scheme, sp.netloc, "", "", ""))


def human_bytes(n: float | None) -> str:
    if not n:
        return "?"
    n = float(n)
    for unit in ("B", "kB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TB"


def fmt_dur(seconds: float) -> str:
    s = int(max(0, seconds))
    d, s = divmod(s, 86400)
    h, s = divmod(s, 3600)
    m, s = divmod(s, 60)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h or d:
        parts.append(f"{h}h")
    if m or h or d:
        parts.append(f"{m}m")
    parts.append(f"{s}s")
    return " ".join(parts)


def fmt_iso(ts: int | None) -> str:
    if not ts:
        return "?"
    return datetime.fromtimestamp(ts, tz=UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---- JWT helpers ---------------------------------------------------------- #
def jwt_claims(token: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("not a JWT (expected 3 dot-separated segments)")
    pad = parts[1] + "=" * (-len(parts[1]) % 4)
    return json.loads(base64.urlsafe_b64decode(pad))


def jwt_times(token: str) -> tuple[int | None, int | None]:
    """Return (exp, nbf) unix timestamps (either may be None)."""
    c = jwt_claims(token)
    return c.get("exp"), c.get("nbf")


def parse_token_response(text: str) -> str:
    """The auth/refresh endpoints return the JWT as a JSON-quoted string."""
    t = text.strip()
    if t.startswith('"'):
        try:
            t = json.loads(t)
        except json.JSONDecodeError:
            t = t.strip('"')
    if not t or t.count(".") != 2:
        raise RuntimeError(f"unexpected token response: {text[:80]!r}")
    return t


# --------------------------------------------------------------------------- #
# Credentials
# --------------------------------------------------------------------------- #
def parse_creds_text(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        m = CREDS_RE.match(raw)
        if not m:
            continue
        key = m.group(1).upper()
        val = (
            m.group(2)
            if m.group(2) is not None
            else (m.group(3) if m.group(3) is not None else m.group(4))
        )
        out[key] = val
    return out


async def read_from_stdin_hidden(prompt: str) -> str:
    """Read a secret from a TTY (hidden) or a plain line from piped stdin."""
    if sys.stdin.isatty():
        return await run_sync(getpass.getpass, prompt)
    line = await run_sync(sys.stdin.readline)
    return line.rstrip("\n")


async def read_line_prompt(prompt: str) -> str:
    if sys.stdin.isatty():
        return await run_sync(input, prompt)
    line = await run_sync(sys.stdin.readline)
    return line.rstrip("\n")


# --------------------------------------------------------------------------- #
# Backend / API
# --------------------------------------------------------------------------- #
@dataclass(slots=True)
class Backend:
    auth_url: str
    image_url: str
    raw_cfg: dict[str, Any]


async def discover_backend(client: httpx.AsyncClient, page_url: str) -> Backend:
    """Replicate the SPA bootstrap to learn the micro-service URLs."""
    origin = origin_of(page_url)
    r = await client.head(origin + "/webclient/", follow_redirects=True)
    cfg_svc = (
        r.headers.get("WebConfigUrl") or r.headers.get("webconfigurl") or origin + "/ConfigService"
    )
    r = await client.get(cfg_svc.rstrip("/") + "/web-config")
    r.raise_for_status()
    cfg = r.json()
    try:
        return Backend(
            auth_url=cfg["authenticationServiceUrl"],
            image_url=cfg["imageServiceUrl"],
            raw_cfg=cfg,
        )
    except KeyError as e:
        raise click.ClickException(f"web-config missing key {e}: {cfg}") from e


async def api_login(client: httpx.AsyncClient, auth_url: str, user: str, pwd: str) -> str:
    payload = {
        "AuthMode": "Credentials",
        "Username": user,
        "Password": pwd,
        "PinCode": "",
        "Mandator": "",
    }
    r = await client.post(auth_url.rstrip("/") + "/auth-user", json=payload)
    if r.status_code != 200:
        raise click.ClickException(f"login failed ({r.status_code}): {r.text[:300]}")
    return parse_token_response(r.text)


async def api_refresh(client: httpx.AsyncClient, auth_url: str, token: str) -> str:
    r = await client.post(
        auth_url.rstrip("/") + "/jwt/refresh",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    if r.status_code != 200:
        raise click.ClickException(f"refresh failed ({r.status_code}): {r.text[:300]}")
    return parse_token_response(r.text)


async def api_list_scans(client: httpx.AsyncClient, image_url: str, token: str) -> list[dict]:
    r = await client.get(
        image_url.rstrip("/") + "/webclient-get-files",
        headers={"Authorization": f"Bearer {token}"},
    )
    r.raise_for_status()
    data = r.json()
    return data if isinstance(data, list) else []


async def api_download_one(
    client: httpx.AsyncClient, image_url: str, token: str, guid: str, dest: Path
) -> int:
    url = image_url.rstrip("/") + "/webclient-download-file/" + guid
    tmp = dest.with_suffix(dest.suffix + ".part")
    total = 0
    async with client.stream("GET", url, headers={"Authorization": f"Bearer {token}"}) as r:
        r.raise_for_status()
        await run_sync(partial(dest.parent.mkdir, parents=True, exist_ok=True))
        async with await anyio.open_file(tmp, "wb") as fh:
            async for chunk in r.aiter_bytes(CHUNK):
                await fh.write(chunk)
                total += len(chunk)
    await run_sync(tmp.replace, dest)
    return total


async def api_delete_one(client: httpx.AsyncClient, image_url: str, token: str, guid: str) -> None:
    r = await client.post(
        image_url.rstrip("/") + "/webclient-delete-files",
        json=[guid],
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=utf-8",
        },
    )
    r.raise_for_status()


# --------------------------------------------------------------------------- #
# Token storage / resolution
# --------------------------------------------------------------------------- #
def save_token_file(path: str, token: str) -> None:
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(token, encoding="utf-8")
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass


async def resolve_token(ctx: click.Context) -> str:
    obj = _fm(ctx)
    if obj.get("token"):
        return obj["token"]
    env_tok = os.environ.get(JWT_ENV)
    if env_tok:
        return env_tok
    tf = Path(obj["token_file"])
    try:
        t = (await run_sync(tf.read_text, "utf-8")).strip()
    except OSError:
        t = ""
    if t:
        return t
    raise click.ClickException(
        f"No token available. Run `login` first, pass --token, or set ${JWT_ENV}."
    )


def assert_token_alive(token: str) -> None:
    try:
        exp, _ = jwt_times(token)
    except Exception:
        return
    if exp and exp <= int(time.time()):
        raise click.ClickException(
            f"Token expired at {fmt_iso(exp)}. Run `login` again "
            "(refresh needs a still-valid token)."
        )


# --------------------------------------------------------------------------- #
# Fetch core (shared by `fetch` and `poll`)
# --------------------------------------------------------------------------- #
def _safe_name(name: str) -> str:
    bad = "".join(chr(c) for c in range(32)) + '<>:"/\\|?*'
    cleaned = name.strip().replace("/", "-").replace("\\", "-")
    cleaned = "".join("_" if ch in bad else ch for ch in cleaned)
    return cleaned or "unnamed.bin"


def _filter_pdfs(items: list[dict], pdf_only: bool) -> list[dict]:
    if not pdf_only:
        return items
    return [it for it in items if str(it.get("FileName", "")).lower().endswith(".pdf")]


def _print_table(items: list[dict]) -> None:
    if not items:
        click.echo("(no documents)")
        return
    rows = [
        (
            i + 1,
            it.get("FileName", ""),
            human_bytes(it.get("FileSizeBytes")),
            it.get("PageCount"),
            it.get("Date", "").replace("T", " ")[:19],
            it.get("Guid", ""),
        )
        for i, it in enumerate(items)
    ]
    hdr = ("#", "FileName", "Size", "Pages", "Date", "Guid")
    widths = [max(len(str(row[c])) for row in [*rows, hdr]) for c in range(len(hdr))]
    for r in (hdr, *rows):
        click.echo("  ".join(str(c).ljust(widths[i]) for i, c in enumerate(r)))


@dataclass(slots=True)
class DownloadResult:
    """One successfully-downloaded document."""

    guid: str
    """the document's server-side identifier"""

    name: str
    """the document's file name, as reported by the server"""

    size: int
    """size of the downloaded file, in bytes"""

    path: Path | None
    """where the file was stored, if it was downloaded"""


async def do_fetch(
    client: httpx.AsyncClient,
    backend: Backend,
    token: str,
    *,
    download_dir: str | None,
    delete: bool,
    pdf_only: bool,
    json_out: bool,
    verbose: bool = True,
) -> tuple[int, list[DownloadResult]]:
    """List documents and optionally download/delete.

    Returns the number of listed documents and the successfully
    downloaded ones.
    """
    items = _filter_pdfs(await api_list_scans(client, backend.image_url, token), pdf_only)

    if json_out:
        click.echo(json.dumps(items, ensure_ascii=False, indent=2))
        return len(items), []

    _print_table(items)
    if verbose:
        click.echo(f"— {len(items)} document(s)")

    if not items:
        return 0, []

    downloads: list[DownloadResult] = []
    if download_dir or delete:
        out_base = Path(download_dir) if download_dir else None
        for idx, it in enumerate(items, 1):
            guid = str(it.get("Guid") or "")
            fname = str(it.get("FileName") or f"{guid}.bin")
            tag = f"[{idx}/{len(items)}] {fname}"

            if out_base is not None:
                dest = out_base / _safe_name(fname)
                try:
                    got = await api_download_one(client, backend.image_url, token, guid, dest)
                except Exception as exc:
                    click.echo(f"{tag}  ✗ download FAILED: {exc}", err=True)
                    continue
                extra = ""
                ann = it.get("FileSizeBytes")
                if ann is not None and got != ann:
                    extra = f"  (announced {ann}, got {got} — WARNING)"
                click.echo(f"{tag}  ↓ {human_bytes(got)} -> {dest}{extra}")
                downloads.append(DownloadResult(guid=guid, name=fname, size=got, path=dest))

            if delete:
                try:
                    await api_delete_one(client, backend.image_url, token, guid)
                    click.echo(f"{tag}  🗑 deleted (guid {guid})")
                except Exception as exc:
                    click.echo(f"{tag}  ✗ delete FAILED: {exc}", err=True)

    return len(items), downloads


# --------------------------------------------------------------------------- #
# MoaT-Link notifications
# --------------------------------------------------------------------------- #
NOTIFY_SCAN = "notify.scan"


def _notify_doc_msg(doc: DownloadResult) -> dict[str, Any]:
    """Build the notification message for one downloaded document."""
    msg: dict[str, Any] = {
        "title": "Scan downloaded",
        "msg": f"{doc.name} ({human_bytes(doc.size)})",
        "prio": "info",
        "name": doc.name,
        "size": doc.size,
    }
    if doc.path is not None:
        msg["path"] = str(doc.path)
    return msg


def _notify_docs_msg(docs: list[DownloadResult]) -> dict[str, Any]:
    """Build a summary notification message for several downloaded documents."""
    total = sum(d.size for d in docs)
    names = ", ".join(d.name for d in docs)
    return {
        "title": f"Scans downloaded ({len(docs)})",
        "msg": f"{len(docs)} document(s), {human_bytes(total)}: {names}",
        "prio": "info",
        "count": len(docs),
        "size": total,
        "names": [d.name for d in docs],
    }


async def notify_scan(
    link: LinkSender,
    docs: list[DownloadResult],
    *,
    mode: str,
) -> None:
    """Send download notifications below the ``notify.scan`` topic.

    With ``mode == "single"`` (or when there's just one document) one
    message per document is sent, at ``notify.scan.doc.<GUID>``; with
    ``mode == "summary"`` a single message at ``notify.scan.docs``
    covers all of them.
    """
    if not docs:
        return
    if mode == "summary" and len(docs) > 1:
        await link.d_set(P(NOTIFY_SCAN) / "docs", _notify_docs_msg(docs))
    else:
        for doc in docs:
            await link.d_set(P(NOTIFY_SCAN) / "doc" / doc.guid, _notify_doc_msg(doc))


async def notify_poll_started(link: LinkSender, interval: float) -> None:
    """Announce that polling has started, at ``notify.scan.poll``."""
    await link.d_set(
        P(NOTIFY_SCAN) / "poll",
        {
            "title": "Scan polling started",
            "msg": f"Polling for new scans every {fmt_dur(interval)}.",
            "prio": "info",
            "interval": interval,
        },
    )


# --------------------------------------------------------------------------- #
# Shared option decorators
# --------------------------------------------------------------------------- #
def connection_opts(fn):
    fn = click.option(
        "--url", default=DEFAULT_PAGE_URL, show_default=True, help="SPA URL of the downloads page."
    )(fn)
    fn = click.option(
        "--creds",
        default=DEFAULT_CREDS,
        show_default=True,
        help="Credential file (USER=/PASS= lines).",
    )(fn)
    fn = click.option(
        "--token-file",
        "token_file",
        default=_default_token_file(),
        show_default=True,
        help="Where login stores / others read the JWT.",
    )(fn)
    fn = click.option(
        "--token", "token", default=None, help="Inline JWT (overrides token-file/env)."
    )(fn)
    fn = click.option(
        "--verify/--no-verify",
        "verify",
        default=False,
        help="Verify TLS (default off: private CA).",
    )(fn)
    return fn


def action_opts(fn):
    fn = click.option(
        "--download",
        "download_dir",
        default=None,
        metavar="DIR",
        help="Save each listed file into DIR.",
    )(fn)
    fn = click.option(
        "--delete", is_flag=True, help="Delete each file from the server (after download)."
    )(fn)
    fn = click.option(
        "--all", "all_exts", is_flag=True, help="Include non-PDF entries (default: PDFs only)."
    )(fn)
    fn = click.option("--json", "json_out", is_flag=True, help="Emit machine-readable JSON.")(fn)
    return fn


def _mk_client(obj: dict) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        verify=obj.get("verify", False),
        timeout=TIMEOUT,
        headers={"User-Agent": "followmeprint_dl/2.0", "Accept": "*/*"},
    )


def _fm(ctx: click.Context) -> dict:
    """This command group's parameters, stored below the shared context object."""
    obj = ctx.obj
    fm = obj.get("fm") if obj is not None else None
    if fm is None:
        raise click.ClickException("Internal error: no 'fm' context. Run via 'moat dev followme'.")
    return fm


@asynccontextmanager
async def _open_link(ctx: click.Context, *, notify: bool) -> AsyncIterator[LinkSender | None]:
    """Connect to MoaT-Link, using the standard ``link`` configuration.

    Yields the link sender, or ``None`` if @notify is not set.
    """
    if not notify:
        yield None
        return

    from moat.link.client import Link  # noqa: PLC0415

    obj = ctx.obj
    try:
        CFG.with_("moat.link")
        lcfg = obj.cfg.link
    except AttributeError:
        raise click.ClickException(
            "No MoaT-Link configuration. Run this command via 'moat'."
        ) from None
    async with Link(lcfg) as sdr:
        yield sdr


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.version_option(message="%(prog)s %(version)s")
@connection_opts
@click.pass_obj
async def cli(
    obj: Any, url: str, creds: str, token_file: str, token: str | None, verify: bool
) -> None:
    """Follow-Me-Print (SafeQ Rubicon) downloader / deleter."""
    fm = obj.get("fm") if obj is not None else None
    if fm is None:
        fm = {}
        if obj is None:
            obj = fm
        else:
            obj["fm"] = fm
    fm.update({
        "url": url,
        "creds": creds,
        "token_file": token_file,
        "token": token,
        "verify": verify,
    })


# ----- login --------------------------------------------------------------- #
@cli.command(help="Authenticate and print a JWT (saved to --token-file).")
@click.option(
    "--save/--no-save",
    "save",
    default=True,
    help="Persist the token to --token-file (default: yes).",
)
@click.option(
    "--show/--no-show", "show", default=True, help="Echo the token to stdout (default: yes)."
)
@click.pass_context
async def login(ctx: click.Context, save: bool, show: bool) -> None:
    obj = _fm(ctx)
    user = await read_line_prompt("Username: ")
    if not user:
        raise click.ClickException("Username is required.")
    pwd = await read_from_stdin_hidden("Password: ")
    if not pwd:
        raise click.ClickException("Password is required.")

    async with _mk_client(obj) as client:
        backend = await discover_backend(client, obj["url"])
        token = await api_login(client, backend.auth_url, user, pwd)

    exp, nbf = jwt_times(token)
    now = int(time.time())
    remaining = exp - now if exp else None
    lifetime = (exp - nbf) if (exp and nbf) else None

    if show:
        click.echo(token)  # pure token on stdout (script-friendly)
    click.echo(
        f"# valid for {fmt_dur(remaining) if remaining else '?'}  (until {fmt_iso(exp)})", err=True
    )
    if lifetime:
        click.echo(f"# nominal lifetime {fmt_dur(lifetime)}", err=True)

    if save:
        save_token_file(obj["token_file"], token)
        click.echo(f"# token saved to {obj['token_file']} (chmod 600)", err=True)


# ----- refresh ------------------------------------------------------------- #
@cli.command(help="Exchange a still-valid token for a fresh one (reset 7-day clock).")
@click.option(
    "--save/--no-save",
    "save",
    default=True,
    help="Persist the new token to --token-file (default: yes).",
)
@click.option(
    "--show/--no-show", "show", default=False, help="Echo the new token to stdout (default: no)."
)
@click.pass_context
async def refresh(ctx: click.Context, save: bool, show: bool) -> None:
    obj = _fm(ctx)
    token = await resolve_token(ctx)
    assert_token_alive(token)

    async with _mk_client(obj) as client:
        backend = await discover_backend(client, obj["url"])
        new_token = await api_refresh(client, backend.auth_url, token)

    exp, nbf = jwt_times(new_token)
    now = int(time.time())
    remaining = exp - now if exp else None
    lifetime = (exp - nbf) if (exp and nbf) else None

    if show:
        click.echo(new_token)
    click.echo(
        f"# refreshed; valid for {fmt_dur(remaining) if remaining else '?'}"
        f"  (until {fmt_iso(exp)})",
        err=True,
    )
    if lifetime:
        click.echo(f"# nominal lifetime {fmt_dur(lifetime)}", err=True)

    if save:
        save_token_file(obj["token_file"], new_token)
        click.echo(f"# token saved to {obj['token_file']} (chmod 600)", err=True)


# ----- fetch --------------------------------------------------------------- #
@cli.command(help="List documents on the #/download page (optionally download/delete).")
@action_opts
@click.pass_context
async def fetch(
    ctx: click.Context, download_dir: str | None, delete: bool, all_exts: bool, json_out: bool
) -> None:
    obj = _fm(ctx)
    token = await resolve_token(ctx)
    assert_token_alive(token)

    async with _mk_client(obj) as client:
        backend = await discover_backend(client, obj["url"])
        _, _downloads = await do_fetch(
            client,
            backend,
            token,
            download_dir=download_dir,
            delete=delete,
            pdf_only=not all_exts,
            json_out=json_out,
        )


# ----- poll ---------------------------------------------------------------- #
@cli.command(help="Repeatedly fetch every N seconds (Ctrl-C to stop).")
@click.option(
    "-i", "--interval", type=float, default=30.0, show_default=True, help="Seconds between rounds."
)
@click.option("--rounds", type=int, default=None, help="Stop after N rounds (default: forever).")
@click.option(
    "--notify/--no-notify",
    "notify",
    default=False,
    help='Send MoaT-Link notifications below the "notify.scan" topic.',
)
@click.option(
    "--notify-mode",
    type=click.Choice(["single", "summary"]),
    default="single",
    show_default=True,
    help="With multiple documents: one message each, or a summary.",
)
@action_opts
@click.pass_context
async def poll(
    ctx: click.Context,
    interval: float,
    rounds: int | None,
    notify: bool,
    notify_mode: str,
    download_dir: str | None,
    delete: bool,
    all_exts: bool,
    json_out: bool,
) -> None:
    obj = _fm(ctx)
    token = await resolve_token(ctx)
    assert_token_alive(token)

    async with (
        _mk_client(obj) as client,
        _open_link(ctx, notify=notify) as link,
    ):
        backend = await discover_backend(client, obj["url"])
        if link is not None:
            await notify_poll_started(link, interval)
        n = 0
        try:
            while rounds is None or n < rounds:
                n += 1
                stamp = time.strftime("%Y-%m-%d %H:%M:%S")
                if not json_out:
                    click.echo(f"==== round {n} @ {stamp} ====")
                try:
                    _, downloads = await do_fetch(
                        client,
                        backend,
                        token,
                        download_dir=download_dir,
                        delete=delete,
                        pdf_only=not all_exts,
                        json_out=json_out,
                        verbose=not json_out,
                    )
                except httpx.HTTPStatusError as exc:
                    if exc.response.status_code == 401:
                        click.echo("token rejected (401) — run `login` again.", err=True)
                        break
                    click.echo(f"round {n} error: {exc}", err=True)
                except Exception as exc:
                    click.echo(f"round {n} error: {exc}", err=True)
                else:
                    if link is not None and downloads:
                        await notify_scan(link, downloads, mode=notify_mode)

                if rounds is not None and n >= rounds:
                    break
                await anyio.sleep(interval)
        except (KeyboardInterrupt, anyio.get_cancelled_exc_class()):
            click.echo("\npoll stopped.")


if __name__ == "__main__":
    cli()
