#!/bin/sh

set -exu

P=python3

mkdir -p inc

$P code/values.py <input/meta/values.csv >inc/enum.yaml
$P code/alarms.py <input/meta/alarms.csv >inc/alarm.yaml
$P code/data.py -i universal <input/meta/universal.csv >inc/universal.yaml
# $P code/data.py -i modbus <input/meta/modbus_tick.csv >inc/modbus.yaml

for f in input/*.csv; do
    n=$(basename $f .csv)
    if [ "$n"= "buffer" ] ; then continue; fi

    $P code/data.py <$f >$n.yaml
done

