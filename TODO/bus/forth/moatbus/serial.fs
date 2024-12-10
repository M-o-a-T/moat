
\ Forth version of a serial bus interface

#require time lib/timeout.fs
#require class: lib/class.fs
#require var> lib/vars.fs
#require crc lib/crc.fs
#require term lib/mt-term.fs

#include {moat}/moatbus/message.fs

#set-flag ring-var int
#include lib/ring.fs

forth only definitions

#if undefined h.1
: h.1 base @ hex swap . base ! ;
#endif

#if undefined ri8
ring-int class: ri8
8 constant elems
;class
#endif

#if undefined moat
#include ../moat-bus/moatbus/message.fs
#else
#if moat undefined bus
#include ../moat-bus/moatbus/message.fs
#endif
#endif

moat also
#if defined serial
serial also definitions
#else
moat definitions
voc: serial
#endif
moat ignore

#if defined ~S
moat handler ignore
#end
#endif

moat msg also

8 $AC9A crc _t16: crctab

voc: ~S
0 constant utf8
1 constant idle
2 constant init
3 constant len
4 constant len2
5 constant data
6 constant crc1
7 constant crc2

#if-flag debug_wire
: .name ( state -- )
  case
    idle of ." idle" endof
    init of ." init" endof
    len of ." len" endof
    len2 of ." len2" endof
    data of ." data" endof
    crc1 of ." crc1" endof
    crc2 of ." crc2" endof
    utf8 of ." utf8" endof
    ." ??:" dup .
  endcase
;
#endif
;voc

voc: ~err
1 constant overflow
2 constant lost
3 constant spurious
4 constant crc
;voc

class: %hdl
__data
  ri8 field: writeq
  ri8 field: readq
  ri8 field: sentq

  task %var field: t_reader
  task %var field: t_writer
  task %var field: t_timeout

  var> int field: msg_in

  var> int field: \emit       \ emit a character
  var> int field: \emit-done  \ terminate emitting
  var> int field: \process    \ incoming message

  var> hint field: \timer
  var> hint field: crc_out
  var> hint field: crc_in
  var> hint field: len_in

#if-flag serial_stats
  var> int field: pkt_in
  var> int field: pkt_out
  var> int field: out_ack_miss
  var> int field: in_crc_err
#endif

  var> cint field: state
  var> cint field: idle
__seal

: ? ( hdl -- )
  ." Ser:" dup hex. 
  dup __ state @ ~s .name space
  dup __ writeq empty? 0= if ." WriteQ " dup __ writeq ? then
  dup __ readq empty? 0= if ." ReadQ " dup __ readq ? then
  dup __ sentq empty? 0= if ." SentQ " dup __ sentq ? then
  drop
;

: alloc_in ( hdl -- )
  dup __ msg_in @ ?dup if
    nip
  else
    130 moat msg alloc
    tuck swap __ msg_in !
  then
  %msg >recv
;

: _emit ( char hdl -- )
  dup __ \emit @ execute
;

: _send ( msg hdl -- )
  swap >r ( hdl |R> msg )
  r@ %msg >send
  r@ %msg prio @ ?dup if
    1- dup 7 lshift or $81 and 1+
    \ $01 / $02 / $81 / $82
  else
    $81
  then
  over __ _emit
  r@ %msg len @ dup $7f > if
    2dup 7 rshift $80 or swap __ _emit
    $7f and
  then
  over __ _emit
  r> 0   ( hdl msg crc )
  over %msg len @  0  do
    over %msg @  ( hdl msg crc char )
    tuck
    crctab  crc crc16
    ( hdl msg char crc' )
    swap
    3 pick __ _emit
  loop nip  ( hdl crc )
  dup $ff and -rot 8 rshift ( crcl hdl crch )
  over __ _emit
  tuck __ _emit
  ( hdl )
  dup __ \emit-done @ execute
;

: send-ack ( hdl -- )
  $06 over dup __ \emit @ execute
  dup __ \emit-done @ execute
;

task subtask class: _t_reader
\ task for processing incoming messages
: \main
  task this checkarg @ >r
  begin
    r@ %hdl readq @
    r@ dup %hdl \process @ execute
    r@ %hdl send-ack
  again
;
;class

task subtask class: _t_writer
\ task for sending messages
: \main
  task this checkarg @ >r
  begin
    r@ %hdl writeq @
#if-flag serial_stats
    r@ __ out_ack_miss @ swap ( cnt msg )
    1 r@ __ out_ack_miss +!
#endif
    dup r@ %hdl _send
    r@ %hdl \timer @ 10 *  time millis
#if-flag serial_stats
    \ compare ack counts. If equal, we got an ack: set prio to zero.
    swap r@ __ out_ack_miss @ <> 1 and over %msg prio !
#endif
    %msg done
  again
;
;class

task subtask class: _t_timeout
\ task for sending messages
%hdl ?? ..
: \main
  task this checkarg @ >r
  begin
    r@ %hdl state @
    ~s idle = if
      task stop
    else
      r@ %hdl idle @ 2 > if
        ~s idle r@ %hdl state !
      else
        1 r@ %hdl idle +!
        r@ %hdl \timer @  time millis
      then
    then
  again
;
;class

: setup
  >r
  ~s idle r@ __ state !
  s" emit-char" voc-xt  r@ __ \emit !
  s" emit-done" voc-xt  r@ __ \emit-done !
  s" process" voc-xt  r@ __ \process !
  s" timer" voc-eval  r@ __ \timer !

  r@ __ writeq >setup
  r@ __ readq >setup
  r@ __ sentq >setup

  _t_timeout [mem-sz] forth mem alloc
  dup _t_timeout >setup
  r@ over _t_timeout checkarg !
  dup _t_timeout start
  r@ __ t_timeout !

  _t_reader [mem-sz] forth mem alloc
  dup _t_reader >setup
  r@ over _t_reader checkarg !
  dup _t_reader start
  r@ __ t_reader !

  _t_writer [mem-sz] forth mem alloc
  dup _t_writer >setup
  r@ over _t_writer checkarg !
  dup _t_writer start
  r@ __ t_writer !

  r@ alloc_in
  rdrop
;

: send ( msg hdl -- )
  __ writeq !
;

: \recv-go ( prio hdr -- )
  dup __ alloc_in
  tuck __ msg_in @  %msg prio !
  ~s len over __ state !
  0 over __ idle !
  0 swap __ crc_in !
;

: process_ack  ( hdl -- )
\ incoming ACK.
#if-flag serial_stats
  -1 over __ out_ack_miss +!
#endif
  __ t_writer @ continue
;

: recv ( char hdl -- char 1 | 0 )
\ character input. Returns False if part of a packet.
  >r
  r@ __ state @
  0 r@ __ idle !
  case
    ~s idle of  ( char )
      dup 6 = if
        drop
        r@ __ process_ack
      else dup $01 = over $02 = or if
        r@ __ \recv-go

      else dup $81 = over $82 = or if
        $7E - r@ __ \recv-go

      else
        dup not $C0 and 0= if
          \ UTF-8 leader
          $ff xor clz 25 - r@ __ len_in !
          ~s utf8 r@ __ state !
          r@ __ t_timeout @ un-idle
        then
        rdrop 1 exit
      then then then
      endof
    ~s utf8 of
      not $C0 and if \ bad char
        0 r@ __ len_in !
      else
        -1 r@ __ len_in +!
      then
      r@ __ len_in @ 0= if
        ~s idle r@ __ state !
      then
      rdrop 0 exit
      endof
    ~s len of
      dup $80 and if
        $80 bic 7 lshift
        ~s len2
      else
        ~s data
      then
      r@ __ state !
      r@ __ len_in !
      endof
    ~s len2 of
      r@ __ len_in +!
      ~s data r@ __ state !
      endof
    ~s data of
      dup r@ __ msg_in @  %msg !
      r@ __ crc_in @ swap crctab  crc crc16  r@ __ crc_in !
      r@ __ len_in @ 1- ?dup if
        r@ __ len_in !
      else
        ~s crc1 r@ __ state !
      then
      endof
    ~s crc1 of
      8 lshift r@ __ crc_in .. hxor!
      ~s crc2 r@ __ state !
      endof
    ~s crc2 of
      r@ __ crc_in @ xor if
#if-flag serial_stats
        1 r@ in_crc_err +!
#endif
      else
        r@ __ msg_in @ 
        0 r@ __ msg_in !
        dup %msg >read
        dup %msg reduce
        r@ __ readq !
      then
      ~s idle r@ __ state !
      endof
  endcase
  r> __ t_timeout @ un-idle
  0
;

;class


forth only definitions

\ SPDX-License-Identifier: GPL-3.0-only
#ok depth 0=
