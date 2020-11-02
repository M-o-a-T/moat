
if [ $# -lt 1 ] || [ -z "$1" ] ; then
	echo "Usage: $0 pill_name …" >&2
	exit 2
fi

CFG="${CFG:-./cfg}"
PILL="$1"
shift

. "$CFG/common"
. "$CFG/pill_$PILL"
