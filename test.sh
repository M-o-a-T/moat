#!/bin/sh

set -uxe
chip="gpio-mockup-A"
cur="$(pwd)"

rmmod gpio-mockup >/dev/null 2>&1 || true
if lsmod | grep -sq gpio-mockup  ; then
	echo "Could not remove the gpio-mockup module. Exiting." >&2
	exit 1
fi
modprobe gpio-mockup gpio_mockup_ranges=-1,8
cd /sys/class/gpio/
for d in gpiochip* ; do
	if test "$(cat $d/label)" = "$chip" ; then
		D=$d
		break
	fi
done
E="/sys/kernel/debug/gpio-mockup-event/$chip"
H="$(hostname | sed -e 's/\..*//')"
cd "$cur"

export PYTHONPATH=.:../asyncgpio

distkv client gpio port -t input -m read -a dest "test a b gpio one" $H $chip 1
distkv client gpio port -t input -m count -a dest "test a b gpio two" $H $chip 2

distkv client data set -ev False test a b gpio three
distkv client data set -ev False test a b gpio four
distkv client data set -ev False test a b gpio five

distkv client gpio port -t output -m write -a src "test a b gpio three" -a state "test a b gpio three state" $H $chip 3
distkv client gpio port -t output -m oneshot -a src "test a b gpio four" -a state "test a b gpio four state" -a t_on 3 $H $chip 4
distkv client gpio port -t output -m pulse -a src "test a b gpio five" -a state "test a b gpio five state" -a t_on 3 -a t_off 5 $H $chip 5

cat <<END
All set up. Now, from a different terminal, play with setting "test a b gpio three" through "five"
and/or "echo -n 1 >/sys/kernel/debug/gpio-mockup-event/gpiochip3/1" or 2.

You can observe GPIO states with "cat /sys/kernel/debug/gpio".

TODO: automate that. As kernels on all those test VMs out there don't compile
the gpio-mockup module, I didn't do that yet. Feel free.
END

distkv -vvvv client gpio monitor $H $chip &
pid=$!
trap 'kill -9 $pid' 0 1 2 15

pat() {
	p=$1
	z=1
	shift
	for k ; do
		echo -n $z > $E/$p
		z=$(expr 1 - $z )
		sleep $k
	done
	echo -n 0 > $p
}

# simulate a bouncing button
pat 2 0.01 .1 .2 

sleep 300
