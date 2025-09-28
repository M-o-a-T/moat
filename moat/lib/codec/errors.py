"""
FUSE operations for MoaT-micro-FS
"""

from __future__ import annotations

from moat.lib.codec.proxy import as_proxy
from moat.util.exc import ExpAttrError, ExpKeyError

try:
    from moat.lib.cmd.errors import RemoteError
except ImportError:

    class RemoteError(RuntimeError):  # noqa: D101
        pass


@as_proxy("_rErrS")
class SilentRemoteError(RemoteError):
    """
    Forwarded error from a remote system.

    Unlike `RemoteError`, this should not trogger a stack dump.
    """


@as_proxy("_NPErr")
class NoPathError(KeyError):
    """An error that marks a nonexisting path"""

    def __str__(self):
        from moat.util import Path  # noqa: PLC0415

        return (
            f"‹NoPath {self.args[0]} {Path.build(self.args[1])}"
            f"{' ' + ' '.join(str(x) for x in self.args[2:]) if len(self.args) > 2 else ''}›"
        )

    def prefixed(self, path):
        "prefix the error's path with another"
        return NoPathError(path / self.args[0], *self.args[1:])


try:
    FileNotFoundError  # noqa:B018  # pyright:ignore
except NameError:

    class FileNotFoundError(SilentRemoteError):  # noqa:A001
        "standard exception"

        def __reduce__(self):
            return (FileNotFoundError, (self.args[0],), {})


as_proxy("_FnErr", FileNotFoundError)

try:
    FileExistsError  # noqa:B018  # pyright:ignore
except NameError:

    class FileExistsError(SilentRemoteError):  # noqa:A001
        "standard exception"

        def __reduce__(self):
            return (FileExistsError, (self.args[0],), {})


as_proxy("_FxErr", FileExistsError)

as_proxy("_KyErr", KeyError)
as_proxy("_EKyErr", ExpKeyError)
as_proxy("_AtErr", AttributeError)
as_proxy("_EAtErr", ExpAttrError)
as_proxy("_NiErr", NotImplementedError)
as_proxy("_StpIter", StopAsyncIteration)

as_proxy("_RemErr", RemoteError)
as_proxy("_SRemErr", SilentRemoteError)


@as_proxy("_StpErr")
class StoppedError(Exception):
    "Called command/app is not running"


@as_proxy("_rErrCCl")
class ChannelClosed(RuntimeError):
    "Link closed."
