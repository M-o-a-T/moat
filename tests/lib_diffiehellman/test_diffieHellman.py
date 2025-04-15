# ${PROJECTNAME}
# (c) Chris von Csefalvay, 2015.

"""
test_diffieHellman tests the DiffieHellman class.
"""

from __future__ import annotations

import unittest

from moat.lib.diffiehellman import DiffieHellman

# pylint: disable=missing-function-docstring,missing-class-docstring


class TestDiffieHellman(unittest.TestCase):
    def setUp(self):
        self.alice = DiffieHellman()
        self.bob = DiffieHellman()

    def test_equality_of_keys(self):
        self.alice.generate_public_key()
        self.bob.generate_public_key()

        alices_shared_key = self.alice.generate_shared_secret(self.bob.public_key)
        bobs_shared_key = self.bob.generate_shared_secret(self.alice.public_key)

        assert alices_shared_key == bobs_shared_key, (
            "There is a mismatch between two shared secrets. Both shared secrets should be the same. This is bad."
        )

    def test_decorators_private_key(self):
        self.alice.generate_public_key()
        assert "_DiffieHellman__private_key" in self.alice.__dict__

    def test_generate_private_key(self):
        self.alice.generate_private_key()
        assert "_DiffieHellman__private_key" in self.alice.__dict__

    def test_generate_public_key(self):
        self.alice.generate_public_key()
        assert "public_key" in self.alice.__dict__

    def test_verify_public_key(self):
        self.alice.generate_public_key()
        self.bob.generate_public_key()
        assert self.alice.verify_public_key(self.bob.public_key)
        assert not self.alice.verify_public_key(2)
        assert not self.alice.verify_public_key(self.alice.prime - 1)


if __name__ == "__main__":
    unittest.main()
