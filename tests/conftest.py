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
# ResourceWarnings from anyio memory streams created by moat code. Various
# callers across the rpc/link/kv stack (HandlerStream, AlertIter, Link,
# EventQueue, LoopLink, ContextMgr, …) don't always close both halves of
# their memory-object streams, so the orphaned half is reclaimed by GC and
# anyio's `MemoryObject*Stream.__del__` fires a ResourceWarning.
#
# Tracked in beads: moat-gt9 (HandlerStream Queue receive halves), moat-5y9
# (AlertIter Queue send half), moat-8vk (LoopLink raw streams), and a
# comprehensive follow-up for the remaining raw-stream leaks across the
# link/kv/repl stack. Until those are fixed, hide these warnings so
# `-W error` stays usable.
#
# Strategy: anyio's stream classes are dataclasses with `__post_init__`; we
# wrap those to tag every instance at creation time with a marker attribute.
# `__del__` then skips the warning for tagged streams. This catches ALL
# creation paths (direct `create_memory_object_stream`, generic-subscript
# `create_memory_object_stream[T](…)`, `moat.util.queue.Queue`, …) without
# needing to patch the factory class itself, so generics keep working.
# Streams created by anyio's own internals (e.g. the test runner's call
# queue) are properly closed and never trigger `__del__`'s warning path, so
# tagging them is harmless.
#
# Tagging uses an instance attribute (not a WeakSet) deliberately: these
# streams participate in reference cycles, and CPython's cyclic GC clears
# their weakrefs *before* running `__del__`, so a WeakSet membership check
# would already be empty by the time we look.
def _silence_moat_stream_leaks() -> None:
    try:
        import anyio.streams.memory as _mem  # noqa: PLC0415
    except ImportError:
        return

    _MARK = "_moat_stream_owned"
    _orig_send_post = _mem.MemoryObjectSendStream.__post_init__
    _orig_recv_post = _mem.MemoryObjectReceiveStream.__post_init__
    _orig_recv_del = _mem.MemoryObjectReceiveStream.__del__
    _orig_send_del = _mem.MemoryObjectSendStream.__del__

    def _tag_post(orig_post):
        def _post(self) -> None:
            orig_post(self)
            try:
                setattr(self, _MARK, True)
            except AttributeError:
                # Slotted stream (unlikely for anyio's dataclasses) -- can't
                # tag, so it falls through to the original warning.
                pass

        return _post

    def _maybe_skip(orig_del):
        def _del(self) -> None:
            if getattr(self, _MARK, False):
                return  # moat-created stream; leak tracked in beads
            orig_del(self)

        return _del

    _mem.MemoryObjectSendStream.__post_init__ = _tag_post(_orig_send_post)
    _mem.MemoryObjectReceiveStream.__post_init__ = _tag_post(_orig_recv_post)
    _mem.MemoryObjectReceiveStream.__del__ = _maybe_skip(_orig_recv_del)
    _mem.MemoryObjectSendStream.__del__ = _maybe_skip(_orig_send_del)


_silence_moat_stream_leaks()


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
