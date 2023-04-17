"""
Fix-up code for loading MoaT from git. Harmless otherwise.
"""
# pylint: disable=cyclic-import

__path__ = __import__("pkgutil").extend_path(__path__, __name__)

from moat._dev_fix import _fix

_fix()
