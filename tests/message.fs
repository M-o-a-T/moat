\

#include test/reset.fs

#include ../moat-bus/moatbus/message.fs

moat bus also

#if mem ?free 50 <
100 mem add
#endif

#if undefined vmsg
0 variable vmsg
#endif

10 alloc vmsg !

%msg item
: vm vmsg @ ;

1 2 $85 vm hdr!
token 123 vm s!
vm >read
#ok vm len @ 6 =
vm .. 20 dump
vm hdr@
h.s
#ok $85 =
#ok 2 =
#ok 1 =
#ok vm s@ token 123 compare

-3 2 $16 vm hdr!
vm ?
$31 vm !
vm ?
token 23 vm s!
vm >read
#ok vm len @ 5 =
vm hdr@
#ok $16 =
#ok 2 =
#ok -3 =
#ok vm s@ token 123 compare


-3 -2 $1 vm hdr!
token 123 vm s!
vm >read
#ok vm len @ 4 =
vm hdr@
#ok $1 =
#ok -2 =
#ok -3 =
#ok vm s@ token 123 compare


1 -2 $17 vm hdr!
token 123 vm s!
vm >read
#ok vm len @ 5 =
vm hdr@
#ok $17 =
#ok -2 =
#ok 1 =
#ok vm s@ token 123 compare

#if undefined wmsg
0 variable wmsg
#endif

10 alloc wmsg !

%msg item
: wm wmsg @ ;

compiletoram
: mcpy ( bits -- )
  begin 
    dup vm @bf  ( bits flag val )
	2 pick wm !b
	if 0 else vm more?b 0= then
  until
  drop
;

: mcchk
  0 vm pos ! \ rewind
  wm data wm max_len 0 fill
  wm >recv
  mcpy
  wm >read
  wm hdr@
  $17 <> if 0 exit then
  -2 <> if 0 exit then
  1 <> if 0 exit then
  wm s@ s" 123" compare
;

#ok 11 mcchk
#ok 14 mcchk

vm free
wm free

forth definitions only

\ SPDX-License-Identifier: GPL-3.0-only
#ok depth 0=

