from __future__ import annotations  # noqa: D100


def get_version():  # noqa: D103
    import pkg_resources  # noqa: PLC0415

    return pkg_resources.get_distribution("moat-mqtt").version
