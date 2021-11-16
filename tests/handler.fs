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

: ? dup __ ?
  ." Step:" dup __ step @ .
  ." Wire:" dup __ wire_res @ h.1
  dup __ timer_out @ if ." Timer:" dup __ timer_out @ . then
  cr drop
;

: setup
  ." HANDLER:" dup . ." = " hex. cr
;

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

: ?wire ( who hdl -- flag )
\ call "wire" if wires changed
  dup __ wire_out @
  over __ wire_in @
  or
  over __ wire_res @ ( who hdl new old )
  over = if ( who hdl new )
    2drop drop false
  else
    swap 2dup __ wire_res !
    ( who new hdl )
    ." WIRE:" rot . over . cr
    __ wire
    true
  then
;
  
: ?timer ( who hdl -- )
  dup __ timer_out @ if
    0 over __ timer_out !
    ." TIMER:" swap . .s
    \ call timer code as if by "normal" timeout
    __ timer ..  __ timeout
    1
  else
    2drop 0
  then
;

: _dequeue ( id hdl -- )
  dup __ sentq empty? 0= if
    ." OUT: done " over . cr
    dup __ sentq @
    %msg done
  then
  dup __ readq empty? 0= if
    ." IN: recv " over .
    dup __ readq @
    dup %msg ?
    %msg done
  then
  2drop
;

;class

8000 500 mem add-if

testbus mem-sz  mem alloc
testbus item
constant tb1

testbus mem-sz  mem alloc
testbus item
constant tb2
#if defined emit-debug
emit-debug
1 task \int yield-trace !
#endif
tb1 >setup
tb2 >setup

: stp1
  1 tb1 _dequeue
  2 tb2 _dequeue
  tb1 wire_out @ tb2 wire_in !
  tb2 wire_out @ tb1 wire_in !
  1 tb1 ?wire if 0 exit then
  2 tb2 ?wire if 0 exit then
  tb1 timer_out @ 0= tb2 timer_out @ 0= or if
    1 tb1 ?timer if 0 exit then
    2 tb2 ?timer if 0 exit then
  else
    tb1 timer_out @ tb2 timer_out @ < if
      1 tb1 ?timer drop 0 exit
    else
      2 tb2 ?timer drop 0 exit
    then
  then
  1
;

: stp ( -- )
  begin
    cr ." ." cr
    task yield
    task yield
    cr ." ." cr
    stp1 if exit then
    depth abort" Stack error"
    task yield
    task yield
    \ exit if error
    tb1 state @ 0= if exit then
    tb2 state @ 0= if exit then
  tb1 state @ 2 <= tb2 state @ 2 <= and until
;

stp

8 msg alloc
msg %msg item
constant ms

\ first "send" some data

-1 2 $13 ms hdr!
token Hello ms s!

ms .. tb1 send

stp
