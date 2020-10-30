#!/usr/bin/env python
import os
import sys

try:
    from setuptools import setup
    from setuptools.command.test import test as TestCommand

    class PyTest(TestCommand):
        def finalize_options(self):
            TestCommand.finalize_options(self)
            self.test_args = []
            self.test_suite = True  # pylint: disable=attribute-defined-outside-init

        def run_tests(self):
            import pytest

            errno = pytest.main(self.test_args)
            sys.exit(errno)


except ImportError:
    from distutils.core import setup

    PyTest = lambda x: x

except OSError:
    long_description = """\
The MoaT bus is designed to be a simple-to-implement, mostly-self-timing,
collision-resistant, error-resistant, open-collector, multi master bus
system.

Sans-I/O access modules in Python and C are available. Just add timeout
handling – and access to at least two open-collector GPIO wires.
"""

setup(
    name="moatbus",
    use_scm_version={"version_scheme": "guess-next-dev", "local_scheme": "dirty-tag"},
    setup_requires=["setuptools_scm"],
    description="Use the MoaT bus, a fast bus for slow wires",
    long_description=long_description,
    url="https://github.com/M-o-a-T/bus",
    author="Matthias Urlichs",
    author_email="matthias@urlichs.de",
    maintainer="Matthias Urlichs",
    maintainer_email="matthias@urlichs.de",
    keywords=["IoT", "bus", "anyio"],
    license="MIT",
    packages=["moatbus"],
    install_requires=["bitstring","distmqtt","asyncclick","trio"],
    extras_require={":python_version < '3.7'": ["async_generator", "async_exit_stack"]},
    tests_require=["pytest >= 2.5.2", "pytest-cov >= 2.3", "trio >= 0.11"],
    cmdclass={"test": PyTest},
    python_requires=">=3.6",
)
