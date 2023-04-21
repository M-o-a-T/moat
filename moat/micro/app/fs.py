"dummy fs module on the multiplexer"

from ._base import BaseAppCmd


class FsCmd(BaseAppCmd):
    "empty command: not needed on the multiplexer"
    pass  # pylint:disable=unnecessary-pass
