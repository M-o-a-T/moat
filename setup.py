import sys
from pathlib import Path

from setuptools import setup

if sys.version_info[0:2] < (3, 6):
    raise RuntimeError("This package requires Python 3.6+.")

setup(
    name="moat.modbus",
    use_scm_version={"version_scheme": "guess-next-dev", "local_scheme": "dirty-tag"},
    packages=["moat.modbus"],
    url="https://github.com/M-o-a-T/moat.modbus",
    license="MIT",
    author="Matthias Urlichs",
    author_email="<matthias@urlichs.de>",
    description="An async modbus client/server library",
    long_description=Path(__file__).with_name("README.rst").read_text(encoding="utf-8"),
    setup_requires=["setuptools_scm", "pytest-runner"],
    tests_require=["pytest-trio"],
    install_requires=["anyio>=3.0", ],
    extras_require={},
    python_requires=">=3.7",
    classifiers=[
        "Intended Audience :: Developers",
        "Programming Language :: Python :: 3",
        "Framework :: AsyncIO",
        "Framework :: Trio",
        "Intended Audience :: Developers",
        "License :: OSI Approved",
    ],
)
