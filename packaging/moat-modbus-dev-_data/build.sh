#!/bin/sh -ex

D="$(cd "$(dirname "$0")"; pwd)"
export PYTHONPATH="$D"/../..
cd $1/heating/KWB
. code/rebuild.sh
