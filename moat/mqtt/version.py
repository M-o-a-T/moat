from __future__ import annotations


def get_version():
    import pkg_resources

    return pkg_resources.get_distribution("moat-mqtt").version
