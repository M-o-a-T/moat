# noqa:D100
from __future__ import annotations

import pytest

from pydantic import ValidationError

from moat.lib.config.base import BaseModel


def test_add_field():  # noqa:D103
    class TM(BaseModel):
        pass

    tm = TM(a=123)
    assert "a" not in vars(tm)

    TM.add_field_("a", annotation=int)

    assert tm.a == 123
    assert "a" in vars(tm)
    with pytest.raises(ValidationError):
        tm.a = "42"
