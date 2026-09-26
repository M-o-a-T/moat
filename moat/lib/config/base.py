"""
Pydantic base model for MoaT configuration.

This module extends :class:`moat.lib.config.base.BaseModel` with the
features needed by unit-configuration models (see HEAT.md §2.4):

* :class:`moat.lib.path.Path` fields accept a :class:`~moat.lib.path.Path`
  (a YAML ``!P`` tag) or a ``list``/``tuple``; a bare ``str`` is accepted
  only outside YAML context (JSON), so a forgotten ``!P`` in YAML config
  is a validation error.  Paths serialise back as a
  :class:`~moat.lib.path.Path`, surviving the MoaT-Link codec round-trip.
* (Nested) :class:`moat.util.attrdict` input is accepted by
  :meth:`pydantic.BaseModel.model_validate` and by the constructor.
* :meth:`BaseModel.from_cfg` reads a subtree of the current
  :class:`~moat.lib.config.CfgStore` and validates it.
* :meth:`BaseModel.cfg_monitor` ties :class:`moat.lib.config.monitor` to
  re-validation, yielding a fresh typed instance per change.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel as _BaseModel
from pydantic import ConfigDict, ValidationInfo, model_validator
from pydantic.fields import FieldInfo
from pydantic_core import core_schema
from pydantic_variants.core import DecomposedModel

from moat.util import attrdict
from moat.lib.path import P, Path

from collections.abc import AsyncIterator, Mapping
from typing import Any

_logger = logging.getLogger(__name__)

#: Validation context marking data originating from YAML config.  Path
#: fields reject bare dotted strings under this context (a YAML path must
#: use ``!P`` or a list); see :func:`_path_core_schema`.
_CFG_CTX = {"source": "yaml"}


def _path_core_schema(_cls: Any, _source: Any, _handler: Any) -> Any:
    """Pydantic core schema for :class:`moat.lib.path.Path`.

    Accepted input:

    * a :class:`~moat.lib.path.Path` — returned unchanged (this is what
      a YAML ``!P`` tag decodes to);
    * a ``list``/``tuple`` — built via :meth:`Path.build` (list form, for
      compatibility with configs that spell out the elements);
    * a ``str`` — parsed via :func:`moat.lib.path.P`, **but only when the
      validation context does not mark the source as YAML**.

    YAML config has an explicit ``!P`` tag for paths; a bare dotted
    string there is almost always a forgotten tag, so it is rejected when
    the context's ``source`` is ``"yaml"`` (see :meth:`BaseModel.from_cfg`
    and :meth:`BaseModel.cfg_monitor`, which set that context).  Other
    sources — notably JSON, which has no tag — keep accepting strings.

    Every other type is rejected.  Serialisation keeps the
    :class:`~moat.lib.path.Path` object in Python mode (so it round-trips
    through the MoaT-Link CBOR codec) and emits its dotted-string form in
    JSON mode.
    """

    def _validate(value: Any, info: ValidationInfo) -> Path:
        if isinstance(value, Path):
            return value
        if isinstance(value, (list, tuple)):
            return Path.build(tuple(value))
        if isinstance(value, str):
            source = (info.context or {}).get("source")
            if source == "yaml":
                raise ValueError("Bare dotted string is not a Path in YAML config; use '!P'.")
            return P(value)
        raise ValueError(f"Not a Path, list, or str: {type(value).__name__}")

    return core_schema.with_info_plain_validator_function(
        _validate,
        serialization=core_schema.plain_serializer_function_ser_schema(str, when_used="json"),
    )


# Teach pydantic how to handle ``Path``.  Attached once, at import time.
#
# ``moat.lib.path`` intentionally does not depend on pydantic, so the
# pydantic core-schema hook is registered from here (which does).
# ``ty`` cannot resolve the dynamically-discovered dunder protocol;
# the assignment is deliberate.
Path.__get_pydantic_core_schema__ = classmethod(_path_core_schema)  # type: ignore[method-assign]  # ty:ignore[unresolved-attribute]


def _to_plain(value: Any) -> Any:
    """Recursively turn (nested) mappings into plain ``dict`` trees.

    Pydantic's strict mode rejects :class:`moat.util.attrdict` (and other
    non-``dict`` mappings) as model input.  Normalising the whole input
    tree beforehand lets ``model_validate(attrdict(...))`` and constructor
    keyword arguments carrying nested attrdicts validate cleanly.
    """
    if isinstance(value, Mapping):
        return {k: _to_plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_plain(v) for v in value]
    return value


class BaseModel(_BaseModel):
    """
    A BaseModel that accepts field updates.

    Beyond plain pydantic behaviour this base class

    * accepts (nested) :class:`moat.util.attrdict` input,
    * supports :class:`moat.lib.path.Path` fields (see module docstring),
    * offers :meth:`from_cfg` and :meth:`cfg_monitor` for live,
      typed configuration backed by :mod:`moat.lib.config`.
    """

    model_config = ConfigDict(extra="allow", validate_assignment=True, strict=True)

    @model_validator(mode="wrap")
    @classmethod
    def _accept_attrdict(cls, data: Any, handler: Any) -> Any:
        """Normalise attrdict/mapping input before strict validation."""
        return handler(_to_plain(data))

    @classmethod
    def add_field_(cls, name: str, annotation: type[Any] | None, **kw: Any) -> None:
        """
        Add a Pydantic field to this model after class creation.

        Args:
            name: Field name.
            annotation: Python type.

        ``annotation`` as well as any other arguments are forwarded to
        `pydantic.FieldInfo`.
        """
        dec = DecomposedModel(cls)
        dec.model_fields[name] = FieldInfo(annotation=annotation, **kw)
        ncls = dec.build(cls.__name__, cls)
        for k, v in vars(ncls).items():
            setattr(cls, k, v)

    def __getattr__(self, k: str) -> Any:
        """
        Attribute fetch that pydantic-izes extra data if the class is
        extended later on.
        """
        if not k.startswith("_"):
            extra = self.__pydantic_extra__
            if extra is not None and k in extra and k in type(self).__pydantic_fields__:
                super().__setattr__(k, extra.pop(k))
                return vars(self)[k]

        get_attr = getattr(_BaseModel, "__getattr__", None)
        if get_attr is not None:
            return get_attr(self, k)
        raise AttributeError(k)

    @classmethod
    def from_cfg(cls, path: str | Path) -> BaseModel:
        """
        Validate a subtree of the current configuration into this model.

        Args:
            path: Dotted path (``str``) or :class:`~moat.lib.path.Path`
                locating the subtree within the active
                :class:`~moat.lib.config.CfgStore`.

        Returns:
            A validated instance of this model.

        Raises:
            RuntimeError: if no configuration is active.
            pydantic.ValidationError: if the subtree does not satisfy the
                model.

        A missing subtree validates against the model's defaults (empty
        input); an explicitly-*absent* subtree is therefore equivalent to
        reverting to the defaults, matching the live-reload contract of
        HEAT.md §2.4.
        """
        from moat.lib.config import current_cfg  # noqa: PLC0415  # avoid import cycle

        cfg = current_cfg.get()
        if cfg is None:
            raise RuntimeError("No active configuration")
        if isinstance(path, str):
            path = P(path)
        try:
            subtree = cfg.result.get_(path)
        except KeyError:
            subtree = attrdict()
        return cls.model_validate(subtree, context=_CFG_CTX)

    @classmethod
    async def cfg_monitor(
        cls, path: str | Path, *, delay: float = 0.25
    ) -> AsyncIterator[BaseModel]:
        """
        Yield re-validated instances of this model as a config subtree changes.

        This ties :class:`moat.lib.config.monitor` to re-validation: on
        every change of the subtree located at *path* a fresh, typed
        instance is produced and yielded.  An update that fails validation
        is logged and skipped (the previous instance stays in effect),
        matching the live-reload contract of HEAT.md §2.4.

        Args:
            path: Dotted path (``str``) or :class:`~moat.lib.path.Path`
                locating the subtree within the active
                :class:`~moat.lib.config.CfgStore`.
            delay: Debounce delay passed to :class:`moat.lib.config.monitor`.

        Yields:
            Validated instances of this model, one per detected change.

        Raises:
            RuntimeError: if no configuration is active when iteration
                starts.

        Usage::

            async for cfg in MyModel.cfg_monitor(P("dev.heat.target")):
                self.apply(cfg)
        """
        from moat.lib.config import current_cfg, monitor  # noqa: PLC0415  # avoid import cycle

        cfg = current_cfg.get()
        if cfg is None:
            raise RuntimeError("No active configuration")
        if isinstance(path, str):
            path = P(path)
        subtree = cfg.result.get_(path)
        with monitor(subtree, delay=delay) as mon:
            async for _change in mon:
                try:
                    yield cls.from_cfg(path)
                except Exception as exc:  # log-and-skip, per §2.4
                    _logger.warning("Invalid config at %s; keeping previous: %s", path, exc)
