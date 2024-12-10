#set-flag debug_wire

#include lib/mt-term.fs
#include ../moat-bus/moatbus/serial.fs

moat also
moat serial also

%hdl class: testserial
__data
  var> int field: other
  var> int field: in_msg

__seal
3 constant nbits

100 constant timer

\ : ? dup __ ?
\   ." Step:" dup __ step @ .
\   ." Wire:" dup __ wire_res @ h.1
\   dup __ timer_out @ if ." Timer:" dup __ timer_out @ . then
\   cr drop
\ ;

: setup
  ." HANDLER:" dup . ." = " hex. cr
;

#if undefined h.2
: u.2 ( u -- ) 0 <# # # #> type ;
: h.2 ( u -- ) base @ hex swap  u.2  base ! ;
#endif

: emit-char
  __ other @
  __ recv
  if 
    ." C:" h.2 space
  then
;

: emit-done drop ;

: process ( msg hdl -- )
  dup __ in_msg @ ?dup if msg %msg done then
  __ in_msg !
;

;class

task yield

\ task !multi
task !single
1 task \int yield-trace !

task yield

12000 8000 mem add-if
800 500 moat msg mem add-if

testserial object: ts1
testserial object: ts2

ts1 .. hex.
ts2 .. hex.
ts1 .. ts2 other !
ts2 .. ts1 other !

task yield
task yield

8 msg alloc
msg %msg item
constant ms
#ok depth 0=

\ first "send" some data

-1 2 $13 ms hdr!
token Hello ms s!
#ok depth 0=

\ check passthru
31 ts1 recv
#ok ( )
#ok 31 =
#ok depth 0=

ms .. ts1 send

task yield
task yield
task yield

#ok depth 0=
#ok ts2 in_msg @
ts2 in_msg @ msg %msg hdr@
#ok $13 =
#ok 2 =
#ok -1 =
ts2 in_msg @ msg %msg s@
#ok token Hello compare

#ok depth 0=
