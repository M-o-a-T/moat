#!/bin/sh

set -e

apk --no-cache --quiet --no-progress add \
    py3-pip \
    py3-virtualenv \
    py3-magic \
    git
virtualenv --system-site-packages "${VENV}"
export PATH="${VENV}"/bin:"${PATH}"
pip3 install \
    pre-commit \
    pytest-cov \
    pook \
    jmespath
pip3 install .
git fetch origin
pre-commit run -a
coverage report
coverage xml
