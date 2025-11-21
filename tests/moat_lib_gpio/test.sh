#!/bin/sh

set -uxe
chip="gpio-mockup-A"
D=

cd /sys/class/gpio/
for d in gpiochip* ; do
	if test "$(cat $d/label)" = "$chip" ; then
		D=$d
		break
	fi
done
cd

if test -n "$D" ; then exit 0; fi
modprobe gpio-mockup gpio_mockup_ranges=-1,8
