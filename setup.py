from setuptools import setup

LONG_DESC = open("README.rst").read()

setup(
    name="distkv_knx",
    use_scm_version={"version_scheme": "guess-next-dev", "local_scheme": "dirty-tag"},
    description="A distributed no-master key-value store",
    url="https://github.com/smurfix/distknx",
    long_description=LONG_DESC,
    author="Matthias Urlichs",
    author_email="matthias@urlichs.de",
    license="MIT -or- Apache License 2.0",
    packages=["distkv_ext.knx"],
    setup_requires=["setuptools_scm", "pytest-runner", "trustme >= 0.5"],
    install_requires=["distkv >= 0.30.1", "xknx >= 0.11.9.16"],
    tests_require=["trustme >= 0.5", "pytest", "flake8 >= 3.7", "xknx >= 0.11.9.17"],
    keywords=["async", "key-values", "distributed"],
    python_requires=">=3.7",
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Information Technology",
        "License :: OSI Approved :: MIT License",
        "License :: OSI Approved :: Apache Software License",
        "Framework :: AsyncIO",
        "Framework :: Trio",
        "Operating System :: POSIX :: Linux",
        "Programming Language :: Python :: 3.7",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: Implementation :: CPython",
        "Topic :: Home Automation",
        "Topic :: System :: Distributed Computing",
    ],
    zip_safe=True,
)
