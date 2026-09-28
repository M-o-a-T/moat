"""
Operator override items (HEAT.md §2.7).

Each override is a retained MoaT-Link item below ``app.heat.override``.
It holds `None` or nothing (automatic), a plain value, or
``{value, expires, reason}``: ``expires`` is wall-clock time, after which
the override lapses and consumers delete the item. JSON schemas for the
items are published below ``schema.app.heat.override`` so that writes
through MoaT-Link are checked.
"""

from __future__ import annotations

import asyncclick as click
from attrs import define

from moat.lib.path import P
from moat.link.schema import schema_path
from moat.util.time import time

from .link import Override

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from moat.lib.path import Path
    from moat.link.client import LinkSender

__all__ = [
    "OVERRIDES",
    "OVERRIDE_PATH",
    "Item",
    "cli",
    "publish_schemas",
    "reader",
    "set_override",
]

OVERRIDE_PATH = P("app.heat.override")


@define
class Item:
    """One kind of override."""

    kind: type | None
    """The value's type (`bool`, `float`), `None` for structured values."""
    schema: dict[str, Any]
    """JSON schema of a plain value."""
    doc: str
    wrapped_only: bool = False
    """The value must be given in the ``{value: …}`` form."""

    def item_schema(self) -> dict[str, Any]:
        "the schema of the stored item"
        wrapped = {
            "type": "object",
            "properties": {
                "value": {"anyOf": [{"type": "null"}, self.schema]},
                "expires": {"type": "number"},
                "reason": {"type": "string"},
            },
            "required": ["value"],
            "additionalProperties": False,
        }
        alts: list[dict[str, Any]] = [{"type": "null"}, wrapped]
        if not self.wrapped_only:
            alts.insert(1, self.schema)
        return {"anyOf": alts}


OVERRIDES: dict[str, Item] = {
    "wp": Item(bool, {"type": "boolean"}, "Heat pump forced on (true) or off (false)."),
    "pellet": Item(bool, {"type": "boolean"}, "Pellet burner forced on (true) or off (false)."),
    "flow_temp": Item(float, {"type": "number"}, "Flow temperature to use instead of the curve."),
    "pwm": Item(
        float,
        {"type": "number", "minimum": 0, "maximum": 1},
        "Water-pump PWM to use instead of the flow unit's.",
    ),
    "errors": Item(
        None,
        {"type": "object", "additionalProperties": {"type": "integer"}},
        "Errors to inject into the errors unit, by key.",
        wrapped_only=True,
    ),
}
"""The known overrides, by name (the last element of the path)."""


def path(name: str) -> Path:
    "The item path of an override."
    return OVERRIDE_PATH / name


def reader(link: LinkSender, name: str, p: Path | None = None) -> Override[Any]:
    """
    A reader for an override: typed, and deleting the item when it expires.

    Args:
        link: The MoaT-Link client.
        name: The override (a key of `OVERRIDES`).
        p: Its path, if configured differently.
    """
    return Override[Any](link, p or path(name), kind=OVERRIDES[name].kind, clear=True)


async def publish_schemas(link: LinkSender) -> None:
    """Store the schemas of all override items."""
    for name, item in OVERRIDES.items():
        await link.d_set(schema_path(path(name)), item.item_schema(), retain=True, verify=False)


async def set_override(
    link: LinkSender,
    name: str,
    value: Any,
    *,
    duration: float | None = None,
    reason: str | None = None,
) -> None:
    """
    Set (or, with value `None` and no reason, clear) an override.

    Args:
        link: The MoaT-Link client.
        name: The override.
        value: The value; `None`: automatic.
        duration: Let the override lapse after this many seconds.
        reason: Why, for the UI.
    """
    item = OVERRIDES[name]
    if value is None and duration is None and reason is None and not item.wrapped_only:
        await link.d_set(path(name), retain=True, verify=False)
        return
    data: Any = value
    if duration is not None or reason is not None or item.wrapped_only:
        data = {"value": value}
        if duration is not None:
            data["expires"] = time() + duration
        if reason is not None:
            data["reason"] = reason
    await link.d_set(path(name), data, retain=True, verify=True)


def _parse(name: str, text: str) -> Any:
    kind = OVERRIDES[name].kind
    if text in ("auto", "none", "-"):
        return None
    if kind is bool:
        t = text.lower()
        if t in ("1", "on", "true", "yes", "y"):
            return True
        if t in ("0", "off", "false", "no", "n"):
            return False
        raise click.BadParameter(f"{text!r} is not on/off/auto")
    if kind is float:
        return float(text)
    raise click.BadParameter(f"'{name}' can't be set from the command line")


@click.command(short_help="Set or clear an operator override.")
@click.argument("name", type=click.Choice(sorted(OVERRIDES)))
@click.argument("value")
@click.option("-t", "--time", "duration", type=float, help="Lapse after this many seconds.")
@click.option("-r", "--reason", help="Why (shown to operators).")
@click.option("--schemas", is_flag=True, help="Also (re)publish the override schemas.")
@click.pass_obj
async def cli(
    obj: Any, name: str, value: str, duration: float | None, reason: str | None, schemas: bool
) -> None:
    """
    Set an operator override: NAME is wp, pellet, flow_temp or pwm; VALUE
    is on/off (wp, pellet), a number, or "auto" to clear it.
    """
    from moat.link.client import Link  # noqa: PLC0415

    val = _parse(name, value)
    async with Link(obj.cfg.link) as link:
        if schemas:
            await publish_schemas(link)
        await set_override(link, name, val, duration=duration, reason=reason)
