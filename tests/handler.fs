#set-flag debug_wire

#include ../moat-bus/moatbus/handler.fs

moat also
moat handler also

%hdl class: testbus
__data
  var> hint field: step
  var> hint field: timer_out
  var> cint field: wire_out  \ set_wire affects this
  var> cint field: wire_in   \ wire input?
  var> cint field: wire_res  \ last wire call did this
__seal
3 constant nbits

10 constant timer_a
100 constant timer_b

: get_wire ( hdl -- bits )
  1 over __ step +!
  dup __ wire_out @
  swap __ wire_in @
  or
  ." R: Wire= " dup h.1 cr
;

: set_wire ( bits hdl -- )
  ." T: Wire=" over h.1 cr
  10 over __ step +!
  __ wire_out !
;

: set_timeout ( usecs hdl -- )
  ." T: Timeout=" over . cr
  100 over __ step +!
  __ timer_out !
;

: ?wire ( hdl -- flag )
\ call "wire" if wires changed
  dup __ wire_out @
  over __ wire_in @
  or
  over __ wire_res @ ( hdl new old )
  over = if ( hdl new )
    2drop false
  else
	swap 2dup __ wire_res !
	__ wire
	true
  then
;
  
;class

8000 500 mem add-if

testbus mem-sz  mem alloc
testbus item
constant tb
#if defined emit-debug
emit-debug
1 task \int yield-trace !
#endif
tb >setup

: stp ( -- )
  begin
  cr ." ." cr
  task yield
  tb ?wire 0= if
  tb timer_out @ if
    0 tb timer_out !
    tb t_timeout @ continue
  then then
  task yield
  tb state @ 2 <= until
;

stp

8 msg alloc
msg %msg item
constant ms

\ first "send" some data

-1 2 $13 ms hdr!
token Hello ms s!

ms .. tb send

stp
