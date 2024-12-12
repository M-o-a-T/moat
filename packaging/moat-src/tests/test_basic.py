"""
Empty test file
"""

import moat.src  # pylint: disable=unused-import
from moat.src.test import raises


def test_nothing():
    """
    Empty test
    """
    pass  # pylint: disable=unnecessary-pass
    with raises(SyntaxError):
        raise SyntaxError("foo")

    
