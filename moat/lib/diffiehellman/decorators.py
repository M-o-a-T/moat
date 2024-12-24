#
# The MIT License (MIT)
#
# Copyright (c) 2016 Chris von Csefalvay
#
# Permission is hereby granted, free of charge, to any person obtaining a copy of this software and
# associated documentation files (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge, publish, distribute
# sublicense, and/or sell copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in all copies or
# substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT
# NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM,
# DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE SOFTWARE.
#


"""
decorators declares some decorators that ensure the object has the
correct keys declared when need be.
"""

from __future__ import annotations


def requires_private_key(func):
    """
    Decorator for functions that require the private key to be defined.
    """

    def func_wrapper(self, *args, **kwargs):
        if self._DiffieHellman__private_key is None:  # pylint: disable=protected-access
            self.generate_private_key()
        return func(self, *args, **kwargs)

    return func_wrapper


def requires_public_key(func):
    """
    Decorator for functions that require the public key to be defined.

    By definition, this includes the private key, as such, it's enough
    to use this to effect definition of both public and private key.
    """

    def func_wrapper(self, *args, **kwargs):
        if self.public_key is None:
            self.generate_public_key()
        return func(self, *args, **kwargs)

    return func_wrapper
