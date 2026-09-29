# noqa:D100
from __future__ import annotations

import sys
from importlib import import_module

from sqlalchemy import Column, Integer, event
from sqlalchemy.orm import DeclarativeBase, Mapper, declared_attr

from moat.util import NotGiven

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class Base(DeclarativeBase):
    """Base class which provides automated table name
    and surrogate primary key column.

    """

    @declared_attr.directive
    def __tablename__(cls):
        return cls.__name__.lower()

    id = Column(Integer, primary_key=True)

    def dump(self) -> dict[str, Any]:  # noqa:D102
        res = dict()
        for k in self.__table__.c:
            if k.name == "id" or k.name.endswith("_id"):
                continue
            v = getattr(self, k.name)
            if v is not None:
                res[k.name] = v
        return res

    def apply(self, **kw) -> None:  # noqa:D102
        for k, v in kw.items():
            if v is NotGiven:
                continue
            setattr(self, k, v)


@event.listens_for(Mapper, "before_configured")
def _complete_models() -> None:
    """Import the ``model_`` companion of every loaded ``moat.db.*.model``.

    The ``model_`` modules add relationships that ``back_populates`` in the
    base models refer to. If mappers get configured while one of them is
    missing, configuration fails, and so does importing it later on.
    """
    done: set[str] = set()
    while todo := [
        n
        for n in list(sys.modules)
        if n.startswith("moat.db.") and n.endswith(".model") and n not in done
    ]:
        for name in todo:
            done.add(name)
            try:
                import_module(name + "_")
            except ModuleNotFoundError as exc:
                if exc.name != name + "_":
                    raise
