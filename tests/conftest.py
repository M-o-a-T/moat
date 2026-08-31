from __future__ import annotations  # noqa: D100

import copy
import pytest
from pathlib import Path as FSPath

try:
    import ruyaml as yaml
except ImportError:
    import ruamel.yaml as yaml

from moat.util import NotGiven
from moat.lib import config
from moat.lib.config import CFG
from moat.lib.path import P, Root

config.TEST = True

SafeRepresenter = yaml.representer.SafeRepresenter
SafeRepresenter.add_representer(FSPath, SafeRepresenter.represent_str)

# Silence the spurious "Unclosed <MemoryObject{Send,Receive}Stream>"
# ResourceWarnings coming from `moat.util.queue.Queue`: various callers
# (notably HandlerStream in moat/lib/rpc/stream/base.py for the receive
# halves, and AlertIter in moat/lib/rpc/alert.py for a send half) close
# only one side of their Queues, so the other half is reclaimed by GC and
# anyio's `MemoryObject*Stream.__del__` fires a ResourceWarning. The
# receive-half leak is tracked in moat-gt9; the AlertIter send-half leak
# in moat-5y9. Until those are fixed, hide exactly these warnings so
# `-W error` stays usable -- but only for streams owned by a `Queue`, so
# that genuinely unclosed streams elsewhere remain loud.
#
# Tagging uses an instance attribute (not a WeakSet) deliberately: these
# streams participate in reference cycles, and CPython's cyclic GC clears
# their weakrefs *before* running `__del__`, so a WeakSet membership check
# would already be empty by the time we look.
def _silence_moat_queue_leaks() -> None:
    try:
        import anyio.streams.memory as _mem  # noqa: PLC0415
        from moat.util.queue import Queue as _MoatQueue  # noqa: PLC0415
    except ImportError:
        return

    _MARK = "_moat_queue_owned"
    _orig_queue_init = _MoatQueue.__init__
    _orig_recv_del = _mem.MemoryObjectReceiveStream.__del__
    _orig_send_del = _mem.MemoryObjectSendStream.__del__

    def _queue_init(self, length: int = 0) -> None:  # noqa: ANN001, ANN002
        _orig_queue_init(self, length)
        for half in (self._s, self._r):  # noqa: SLF001
            try:
                setattr(half, _MARK, True)
            except AttributeError:
                # Slotted stream half (unlikely for anyio's dataclasses) --
                # can't tag, so it falls through to the original warning.
                pass

    def _maybe_skip(orig_del):  # noqa: ANN001, ANN202
        def _del(self) -> None:  # noqa: ANN001
            if getattr(self, _MARK, False):
                return  # Queue-owned half; leak tracked separately
            orig_del(self)

        return _del

    _MoatQueue.__init__ = _queue_init
    _mem.MemoryObjectReceiveStream.__del__ = _maybe_skip(_orig_recv_del)
    _mem.MemoryObjectSendStream.__del__ = _maybe_skip(_orig_send_del)


_silence_moat_queue_leaks()


@pytest.fixture(autouse=True, scope="session")
def anyio_backend():
    "never use asyncio for testing"
    return "trio"


@pytest.fixture(autouse=True)
def clear_root():
    "clear root after test"
    yield
    Root.set(NotGiven, force=True)


@pytest.fixture(autouse=True, scope="session")
def in_test(free_tcp_port_factory):
    """
    This fixture ensures that the configuration for moat-link clients
    does not access port 1883 and thus won't disturb / depend on a
    locally runnign MQTT server.
    """
    from moat.lib.config import CFG  # noqa:PLC0415

    def fix_for_testing(cfg):
        if "backend" in cfg.link and cfg.link.backend.get("port", 1883) == 1883:
            cfg.link.backend.port = free_tcp_port_factory()

    CFG.set_env_(P("in_test"), "fix_for_testing")
    try:
        fix_for_testing(CFG)
    except AttributeError:
        pass

    try:
        yield
    finally:
        CFG.set_env_(P("in_test"), NotGiven)


@pytest.fixture
def cfg():
    "fixture for the static config"
    with CFG.with_config_(config.CfgStore()) as c:
        yield copy.deepcopy(c.result.moat)
