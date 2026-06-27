"""Cross-table relationships for rain.

Rain's relationships are all intra-package and are wired directly in
``model.py``. There are no cross-submodule relationships to attach here,
unlike ``moat.db.{box,thing,label}`` which use this module to break
import cycles.

The rich ``apply()`` methods live on the classes in ``model.py`` as real
method overrides (not monkeypatches), per the AGENTS.md no-cast policy:
rain has no import cycle forcing deferral, so a normal override is
preferred over ``Cls.apply = cast(Any, fn)``.
"""
