#!/bin/sh

set -e

apk --no-cache --quiet --no-progress add \
    py3-pip \
    py3-virtualenv \
    py3-magic \
    build-base
virtualenv --system-site-packages "${VENV}"
export PATH="${VENV}"/bin:"${PATH}"
pip3 install poetry
poetry install --with docs
sphinx-build -b html docs build
