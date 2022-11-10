#!/bin/sh

set -e

apk --no-cache --quiet --no-progress add \
    py3-pip \
    py3-virtualenv \
    git
virtualenv "${VENV}"
export PATH="${VENV}"/bin:"${PATH}"
pip3 install \
    pre-commit \
    pytest
git fetch origin
pre-commit run --from-ref origin/"${CI_DEFAULT_BRANCH}" --to-ref HEAD
