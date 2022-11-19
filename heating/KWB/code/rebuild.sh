#!/bin/sh

set -eu

P=python3

mkdir -p inc

test -t 0 && echo -n "\r values             \r"
$P code/values.py <input/meta/values.csv >inc/enum.yaml
test -t 0 && echo -n "\r alarms             \r"
$P code/alarms.py <input/meta/alarms.csv >inc/alarm.yaml
test -t 0 && echo -n "\r universal          \r"
$P code/data.py -i universal <input/meta/universal.csv >inc/universal.yaml
# $P code/data.py -i modbus <input/meta/modbus_tick.csv >inc/modbus.yaml

for f in input/*.csv; do
    n=$(basename $f .csv)
    if [ "$n" = "buffer" ] ; then continue; fi
    test -t 0 && echo -n "\r $n                 \r"

    $P code/data.py <$f >$n.yaml
done
test -t 0 && echo "done.                      "

