
\ Forth version of a bus handler

#require alloc lib/alloc.fs
#require class: lib/class.fs
#require var> lib/vars.fs
#require crc lib/crc.fs

#include {moat}/moatbus/message.fs

#set-flag ring-var int
#include lib/ring.fs

forth only definitions

#if undefined h.1
: h.1 base @ hex swap . base ! ;
#endif

ring-int class: ri8
8 constant elems
;class

#if undefined moat
#include ../moat-bus/moatbus/message.fs
#else
#if moat undefined bus
#include ../moat-bus/moatbus/message.fs
#endif
#endif

moat also
#if defined handler
handler also
#else
moat definitions
voc: handler
#endif
moat ignore

#if defined ~S
moat handler ignore
#end
#endif

moat msg also

\ XXX only works on little endian machines
: _P <builds 
#[if] defined c,
  >r >r -rot swap c, c, c, r> c, r> c,
#else
  >r >r -rot 8 lshift or h, r> 8 lshift or h, r> h,
#endif
  align does> + 2- c@
;
7 5 3 3 2 _P _len
11 14 11 14 11 _P _bits
3 2 1 1 1 _P _n_end

voc: ~S
0 constant error
1 constant wait_idle
2 constant idle
3 constant read
4 constant read_ack
5 constant read_acquire
6 constant read_crc
10 constant write
11 constant write_acquire
12 constant write_ack
13 constant write_end
14 constant write_crc

#if-flag debug_wire
: .name ( state -- )
  case
    error of ." error" endof
    wait_idle of ." wait_idle" endof
    idle of ." idle" endof
    read of ." read" endof
    read_ack of ." read_ack" endof
    read_acquire of ." read_acquire" endof
    read_crc of ." read_crc" endof
    write of ." write" endof
    write_acquire of ." write_acquire" endof
    write_ack of ." write_ack" endof
    write_end of ." write_end" endof
    write_crc of ." write_crc" endof
    ." ??:" dup .
  endcase
;
#endif
;voc

voc: ~err
1 constant nothing
-2 constant collision
-11 constant holdtime
-12 constant acquire
-13 constant crc
-14 constant bad_collision
-16 constant no_change
-20 constant fatal
-21 constant flap
-22 constant acquire_fatal
-31 constant unused
-32 constant unhandled
-33 constant cannot
;voc

voc: ~res
0 constant success
1 constant missing
2 constant error
3 constant fatal
;voc

voc: ~w
0 constant more
1 constant crc
2 constant end
3 constant final
;voc

voc: ~t
0 constant off
1 constant break
2 constant settle
2 constant backoff
5 constant zero
10 constant error
;voc

class: %hdl
__data
  ri8 field: writeq
  ri8 field: readq
  ri8 field: sentq

  var> int field: \get_wire
  var> int field: \set_wire
  var> int field: \set_state
  var> int field: \set_timeout

  task %var field: t_timeout
  task %var field: t_reader
  task %var field: t_written

  var> int field: sending
  var> int field: msg_in

  var> hint field: crc
  var> hint field: backoff
  var> hint field: \timer_a  \ signal timeslot, µsec
  var> hint field: \timer_b  \ propagation delay, µsec
  var> hint field: val
  var> hint field: val_end
  var> hint field: val_max

  var> cint field: wires
  var> cint field: max
  var> cint field: len
  var> cint field: bits
  var> cint field: n_end
  var> cint field: len_crc

  var> cint field: last
  var> cint field: current
  var> cint field: intended
  var> cint field: settle
  var> cint field: nval
  var> cint field: want_prio
  var> cint field: current_prio

  var> cint field: no_backoff
  var> cint field: tries
  var> cint field: last_zero
  var> cint field: flapping

  var> cint field: state
  var> cint field: write_state

  var> cint field: ack_mask
  var> cint field: nack_mask
  var> cint field: ack_masks

  var> cint field: cur_pos
  var> cint field: cur_len
  here: cur_chunk
  8 +
__seal


: transmitted ( msg res hdl -- )
  >r
  swap
  2dup %msg prio !
  r@ __ sentq !
  ( res )
  0 r@ __ tries !
  r@ __ backoff @ dup ~t backoff 2* > if
    2/
  else
    drop ~t backoff
  then r> __ backoff !
;

: set_timeout ( val hdl -- )
\ set the timeout
  >r
  dup ~t break <= if
    r> __ t_timeout @ stop
    drop exit
  then
  dup ~t zero = r> __ last_zero @ and if
    drop r> __ last_zero @ ~t zero >= if
      1
    else
      ~t zero r> __ last_zero @ -
    then
  then
  r> __ last_zero @ ?dup if
    1- ~t zero < if
      dup r> __ last_zero +!
    then
  then ( val )

  ?dup if
    r@ __ \timer_a @ *
  else
    r@ __ \timer_b @
  then
  r> __ t_timeout @ sleep
;

: add_crc ( val hdl -- )
\ CRC add. No table because probably not worth it.
  dup >r __ crc @ xor  $583  r@ __ wires @  forth crc calc
  r> __ crc !
;

: clear_sending ( hdl -- msg )
  0 over __ want_prio !
  dup __ sending @  ( hdl msg )
  0 rot __ sending !
;

: set_ack_mask ( hdl -- )
  >r
  r@ __ settle @ if r@ __ last @ else r@ __ current @ then
  ( bits )
  1 over = if 2 else 1 then r@ __ ack_mask !
  \ (h->WIRES == 2) ? (bits ? 0 : 2) : ((bits == 3) || (bits == 1)) ? 4 : 2
  r@ __ wires @ 2 = if
    if 0 else 2 then
  else
    dup 3 = swap 1 = or if 4 else 2 then
  then
  r@ __ nack_mask !
  r@ __ ack_mask @ r@ __ nack_mask @ or r@ __ ack_masks !
  rdrop
;

: reset ( hdl -- )
  >r
  0 r@ __ intended !
  0 r@ __ cur_pos !
  0 r@ __ cur_len !
  0 r@ __ ack_mask !
  0 r@ __ val !
  0 r@ __ nval !
  false r@ __ settle !
  r@ __ msg_in @ ?dup if
    %msg done
  then
  130 moat msg alloc  dup r@ __ msg_in !
  %msg >recv
  rdrop
;

: start_writer ( hdl -- )
  >r
." SW A " r@ hex. .s
  0 r@ cur_pos !
  0 r@ cur_len !
\ ." SW B " .s
  true r@ settle !
\ ." SW C " .s
  r@ __ sending @ %msg >send
\ ." SW D " .s
  r@ __ want_prio @ r@ dup __ \set_wire @ 
dup ." SW X " .word .s
  execute
\ ." SW E " .s
  ~s write_acquire r@ dup __ \set_state @ 
dup ." SW Y " .word .s
  execute
\ ." SW F " .s
  ~w more r@ __ write_state !
  rdrop
." SW Z " .s
;

: \sn >r
      r@ __ wires @ -
      r@ __ no_backoff @ if
        false r@ __ no_backoff !
        ~t backoff 2+ r@ __ backoff !
      then
      dup r@ __ wires @ >= if
        drop r@ __ wires @ 1-
      then
  rdrop ;

: send_next ( hdl -- )
  >r
." SN A " r@ __ state @ ~s .name space .s
  r@ __ sending @ 0= if
." SN B " .s
    r@ __ writeq empty? if
      rdrop exit
    then
." SN C " .s
    r@ __ writeq @  r@ __ sending !
  then
." SN D " .s
  r@ __ want_prio @ 0= if
." SN E " .s
    r@ __ sending @  %msg prio @
    dup r@ __ wires @ >= if
      r@ \sn
    then ( prio )
    1 swap lshift r@ __ want_prio !
  then
." SN F " r@ __ state @ ~s .name ."  Settle=" r@ __ settle @ . .s
  r@ __ state @ ~s idle =  r@ __ settle @ 0=  and if
." SN G " .s
    r@ __ start_writer
  then
." SN Z " .s
  rdrop
;

: set_state ( state hdr -- )
  >r
  dup r@ __ state @ = if rdrop exit then
." ST A " r@ __ state @ ~s .name space dup ~s .name space .s

#if-flag debug_wire
  dup r@ __ state @
  2dup ~s read >= swap ~s read >= <>
  -rot ~s write >= swap ~s write >= <> or if
    ." SetState: " dup ~s .name cr
  then
#endif
  dup ~s write < r@ __ state @ ~s write >= and if
." ST D " r@ __ state @ ~s .name space .s
    0 r@ dup __ \set_wire @ execute
  then

  dup ~s read_ack = over ~s write_ack = or if
." ST E " .s
    r@ __ set_ack_mask
  then

  dup ~s read_acquire = over ~s write_acquire = or if
." ST F " .s
    false r@ __ no_backoff !
  then

." ST F2 " .s
  dup ~s idle = if
." ST G " .s
#if-flag debug_wire
    r@ __ current @ if
      ." ?? state current" cr
    then
#endif
    r@ __ state !
    true r@ __ settle !

    ~t break 1+ 
    r@ __ no_backoff @ r@ __ sending @ 0<> and if 0 else r@ __ backoff @ then +
    r@ dup __ \set_timeout @ execute

  else dup ~s idle < r@ __ state @ ~s idle > and if
." ST H " r@ __ state @ ~s .name space dup ~s .name space .s
    r@ __ state !
    r@ __ reset
    r@ __ send_next
    r@ __ current @ if
      ~t off
    else r@ __ state @ ~s error = if
      ~t error
    else
      ~t zero 
    then then
    r@ dup __ \set_timeout @ execute
    
  else
." ST I " .s
    r@ __ state !
  then then
." ST K " .s
  rdrop
;

: read_done ( hdl crc_ok? -- )
  swap >r
  false r@ __ no_backoff !
  r@ __ msg_in @
  0 r@ __ msg_in !  ( crc_ok? msg )
  r@ __ readq full? if  \ owch
  swap
#if-flag debug_wire
  ." ReadQ full!" cr
#endif
    drop 0
  then
  if
    %msg reduce
    r@ __ readq !
  else
    %msg done
    \ ~err crc r@ __ report_error
    r@ __ set_ack_mask
    r@ __ nack_mask @ if
      r@ __ nack_mask @ r@ __ ack_mask !
      ~s write_ack \ nack, in this case
    else
      ~s wait_idle
    then
    r@ __ set_state
  then
  rdrop 
;

: error ( err hdl -- )
." ERRA " .s
  >r
  r@ __ state @ ~s error = if
    drop rdrop exit
  then

  dup ~err holdtime = r@ __ current @ 0= and if
." ERRB " .s
    drop
    r@ __ state @ ~s idle < if
      ~s idle
    else
      ~s wait_idle
    then
    r> __ set_state
    exit
  then

  dup 0< if
." ERRC " .s
    r@ __ backoff @  dup ~t backoff 3 * < if
      \ TODO random backoff between 1.5 and 2.5
      7 4
    else
      6 5
    then -rot * swap / r@ __ backoff !
  then
#if-flag debug_wire
  ." Err:" r@ __ state @ ~s .name ."  T:" dup . ." Back:" r@ __ backoff @ . cr
#endif
." ERRD " .s
  \ dup r@ __ report_error
  r@ __ reset
." ERRE " .s
  dup ~err fatal < r@ __ sending @ and if
." ERRF " .s
    r@ __ clear_sending
    ~res fatal r@ __ transmitted
    ~s wait_idle
  else dup 0< swap ~err fatal < and if
." ERRG " .s
    ~s error
  else
." ERRH " .s
    ~s wait_idle
  then then
." ERRY " .s
  r> __ set_state
." ERRZ " .s
;


: read_crc ( hdr -- )
  0 over __ nval !
  0 over __ val !
  ~s read_crc swap __ set_state
;

: \rrn >r
        \ h->val < h->VAL_MAX + (1<<(h->BITS-8)))
        r@ __ val @ r@ __ val_max @ -  r@ __ bits @ 8 -  r@ __ msg_in @ %msg !b
        r@ __ read_crc
  rdrop ;

: \rn >r
    r@ __ nval @ r@ __ len @ = if
      r@ __ val @ r@ __ val_max @ < if
        r@ __ val @  r@ __ bits @  r@ __ msg_in @ %msg !b
        0 r@ __ nval !
        0 r@ __ val !

      else r@ __ val @ r@ __ val_max @ 1 r@ __ bits 8 - lshift + < if
        r@ __ \rrn

      else
        ~err crc r@ __ error
      then then
    then
  rdrop ;

: read_next ( bits hdl -- )
  >r
  r@ last @ xor
  ?dup if
    ~err nothing r> __ error
    exit
  then
  false r@ __ no_backoff !
  \ h->val = h->val * h->MAX + bits-1;
  r@ __ val @ r@ __ max @ * + 1- r@ __ val !
  1 r@ __ nval +!
  r@ __ state @ ~s read_crc = if
    r@ __ nval @ r@ __ len_crc @ = if
#if-flag debug_wire
      ." CRC: loc:" r@ __ crc @ . ." rem:" r@ __ val @ . cr
#endif
      r@ __ val @ r@ __ crc @ =  r@ __ read_done
    then
  else \ ~s read
    r@ __ nval @ r@ __ n_end @ =
    r@ __ val @ r@ __ val_end @ =
    and if
      r@ __ read_crc
    else
      r@ __ \rn
    then

  then
  rdrop
;

: start_reader ( hdl -- )
  ~s read_acquire swap __ set_state
;

: \gc >r
      drop
      ~w final r@ __ write_state !
      r@ dup __ n_end @ tuck 0 do ( len hdr )
        0 over __ cur_chunk i + c!
      loop drop
  rdrop ;

: gen_chunk ( hdl -- )
  >r
." GC A " .s
#if-flag debug_wire
  r@ __ cur_pos @ abort" Pos >0"
#endif

." GC B " .s
  r@ __ write_state @ dup ~w more = if drop
." GC C " .s
    r@ __ sending @ dup %msg more?b if
." GC D " .s
      r@ __ bits @ swap %msg @b
." GC E " .s
      dup r@ __ val_max @ >= if
#if-flag debug_wire
        ." Send Residual:" dup h.1 cr
#endif
        ~w final r@ __ write_state !
      else
#if-flag debug_wire
        ." Send Chunk:" dup h.1 cr
#endif
      then
      0
    else
      r@ \gc
    then

  else ~w crc = if
    rdrop false exit

  else \ ~w end = over ~w final = or if drop
    ~w crc r@ __ write_state !
    ~s write_crc r@ __ set_state
    r@ __ crc @  0
#if-flag debug_wire
    ." Send CRC:" over h.1
#endif

  then then ( val 0 | n )

  ?dup 0= if ( val )
    r@ __ write_state @ ~w crc = if r@ __ len_crc @ else r@ __ len @ then
    ( val len )
    dup r@ __ cur_pos !
    tuck r@ swap 0 do ( len val hdr )
      tuck __ max @ ( len hdr val max )
      /mod ( len hdr p v' )
      -rot 1+ over ( len val hdr p' hdr )
      __ cur_chunk i + c!
    loop 2drop
  then ( n )

  dup r@ __ cur_pos !
  r> __ cur_len !
  true
;

: write_next ( hdr -- )
  >r
  r@ __ cur_pos @ 0= if
    r@ __ gen_chunk 0= if
      ~s read_ack r@ __ set_state
      rdrop false exit
    then
  then

  r@ __ cur_pos @ 1- dup r@ __ cur_pos !
  r@ __ cur_chunk + c@
#if-flag debug_wire           
  dup r@ __ max @ > abort" chunk too big"
#endif
  r@ __ last @ xor r@ __ intended !
  rdrop
  true
;

: write_collision ( bits settled hdr -- )
  >r
  swap dup -1 not and r@ __ want_prio !
#if-flag debug_wire   
  ." WColl " over h.1 dup . cr
#endif
  r@ __ msg_in @ ?dup if %msg done then
  r@ __ sending @
  130 %msg alloc  dup %msg >recv  dup r@ __ msg_in !
  ( settled old new )
  over %msg data @ ( … old new odata )
  over %msg data @ ( … old new odata ndata )
  3 pick %msg pos @ 7 + 3 rshift  move ( … old new )
  swap %msg pos @ swap %msg pos !
  0 r@ __ nval !
  0
  r@ __ cur_len @
  begin ( settled val len )
    dup r@ __ cur_pos @ 1+ > while
    1-
    swap r@ __ max @ * r@ __ cur_chunk 2 pick + c@ + 1- swap
    1 r@ __ nval +!
  repeat
  drop
  r@ __ val !
  ( settled )

  r@ __ current @
  ~s read r@ __ set_state
  swap if
    dup r@ __ add_crc
    r@ __ read_next
  else
    drop
  then
  true r> __ no_backoff !
;

: retry ( msg res hdl -- )
  >r
#if-flag debug_wire
  ." Retry:" dup . cr
#endif
  dup ~res missing = if
    2
  else dup ~res error = if
    4
  else
    6
  then then ( msg res xtries )
." RTA " .s
  r@ __ tries @ 0= if
    r@ __ tries !
  else
    drop
  then ( msg res )
." RTB " .s
  r@ __ tries @ 1 = if
." RTC " .s
    r@ __ transmitted
  else
    \ re-queue, but drop on the floor if q is full.
." RTD " .s
    drop ( msg )
    -1 r@ __ tries +!
    r@ __ sending !
  then
." RTE " .s
  rdrop
;

: \tra >r
    r@ __ clear_sending  ( bits msg )
." TS H " .s
    swap ( msg bits )
    r@ __ ack_mask @ over = if drop
." TS I " .s
      ~res success r@ __ transmitted
    else ?dup 0= if
." TS J " .s
      ~res missing r@ __ retry
    else r@ __ nack_mask @ over = if drop
." TS K " .s
      ~res error r@ __ retry
    else r@ __ ack_masks @ not over and if drop
." TS L " .s
      ~err bad_collision r@ __ error
." TS M " .s
      ~res fatal r@ __ retry
    else drop
." TS N " .s
      ~res missing r@ __ retry
    then then then then
." TS O " .s
rdrop ;
 
: timeout_settle ( hdl -- )
\ process a timeout
  >r
." TS A " .s
  0 r@ flapping !
  r@ __ current @
." CUR=" dup .
  r@ __ state @
." STATE=" dup ~S .name space .s
  case ( bits -- )
  ~s idle of
." TS SI " .s
    r@ __ sending @ if
      true r@ __ settle !
      r@ __ start_writer
    then
    drop
." TS B " .s
    endof
  ~s write_acquire of
." TS C " .s
    r@ __ want_prio @ over = if
." TS D " .s
      r@ __ current_prio !
." TS D1 " .s
      0 r@ __ crc !
." TS E " .s
      ~s write r@ __ set_state
    else
." TS F " .s
      drop ~err acquire_fatal r@ __ error
    then
." TS G " .s
    endof
  ~s read_acquire of
    ?dup if
      dup dup 1- and if \ two bits are set
        drop ~err acquire_fatal r@ __ error
      else
        r@ __ current_prio !
        0 r@ __ crc !
        ~s read r@ __ set_state
      then
    else
      drop ~err nothing r@ __ error
    then
    endof
  ~s read of
    dup r@ __ add_crc
    r@ __ read_next
    endof
  ~s read_crc of
    r@ __ read_next
    endof
  ~s read_ack of
    r@ \tra
    endof
  ~s write of
    r@ __ intended @ over <> if
      r@ __ intended @ not and  true  r@ __ write_collision
    else
      r@ __ add_crc
    then
    endof
  ~s write_crc of
    r@ __ intended @ over <> if
      r@ __ intended @ not and  true  r@ __ write_collision
    else drop
    then
    endof
  ~s write_ack of
    r@ __ ack_masks @ not over and if
      ~err bad_collision r@ __ error drop
    else r@ __ ack_mask @ not over <> if
      ~err bad_collision r@ __ error
      r@ __ ack_masks @ not and  true  r@ __ write_collision
    else
      drop
      ~s write_end r@ __ set_state
    then then 
    endof
  ~s write_end of
    ~err cannot r@ __ error drop
    endof
  ~err unhandled r@ __ error drop
  endcase ( - )
  rdrop
." TS Z " .s
;


: wire_settle ( bits hdl -- )
\ The wire state has changed: now these bits are pulled low.
  >r
#if-flag debug_wire
  ." Wire Settle:" dup h.1
#endif
  r@ __ state @ ~s idle < abort" State?"

  r@ __ state @
  dup ~s idle = if drop
    if \ any bit set?
      r@ __ no_backoff @  r@ __ sending @  and if
        r@ __ start_writer
      else
        r@ __ start_reader
      then
    then
  else dup ~s write_acquire = if drop
    r@ want_prio @ 1- and if
#if-flag debug_wire
      ." PRIO FAIL " dup h.1 r@ want_prio @ h.1 cr
#endif
      drop
      r@ __ start_reader
    then
  else dup ~s write_ack = if drop
    r@ __ ack_masks @ r@ __ last @ or not and if
      ~err bad_collision r@ __ error
    then
  else ~s write >= if
    r@ __ intended @ r@ __ last @ or not and ?dup if
      false r@ __ write_collision
    then
  else
    drop
  then then then then ( - )

  rdrop
;

: next_step ( timeout hdl -- )
  dup >r __ current @ ( timeout bits )
." NS A " .s
  r@ __ state @
  dup ~s idle < if drop
." NS B " .s
    over if
      ~err holdtime r@ __ error 
    else 
      dup if ~t off else ~t zero then r@ dup __ \set_timeout @ execute
    then
  else dup ~s idle = if drop
." NS C " .s
    r@ __ sending @ if
      r@ __ start_writer
    else dup if
        r@ __ start_reader
    then then
  else dup ~s write < if drop
." NS D " .s
    over if
      ~err holdtime r@ __ error
    then
  else dup ~s write_acquire = if drop
." NS E " .s
    dup r@ __ want_prio @ = if
      r@ __ start_writer
      ~s write r@ __ set_state
    else
      ~err acquire_fatal r@ __ error
    then
  else dup ~s write = over ~s write_crc = or if drop
." NS F " .s
    r@ __ write_next if
      dup r@ __ last @ r@ __ intended @ or bic if
        dup r@ __ intended @ bic false r@ __ write_collision
      else
        r@ __ intended @ r@ dup __ \set_wire @ execute
      then
    then
  else dup ~s write_ack = if drop
." NS G " .s
    dup r@ __ last @ r@ __ ack_masks @ or bic if
      ~err bad_collision r@ __ error
    else
      r@ __ ack_mask @ r@ dup __ \set_wire @ execute
    then
  else dup ~s write_end = if drop
." NS H " .s
    ~s wait_idle r@ __ set_state
  else
    drop
." NS I " .s
    ~err unhandled r@ __ error
  then then then then then then then
  2drop rdrop
." NS Z " .s
;

: \mt >r
." TD " .s
      r@ %hdl timeout_settle
\ ." TE " .s
      r@ %hdl current @ r@ %hdl last !
\ ." TF " .s
      r@ %hdl state @ dup ~s write >= if drop
\ ." TG " .s
        ~t break r@ dup %hdl \set_timeout @ execute
      else ~s idle > if
\ ." TH " .s
        ~t zero r@ dup %hdl \set_timeout @ execute
      then then
." TI " .s
  rdrop ;

task subtask class: _t_timeout
\ task for handling timeouts
: \main
  task this checkarg @ >r
  begin
." TTA " .s
    task stop
#if-flag debug_wire
    ." TimerS " .s
#endif
    r@ %hdl settle @ if
      false r@ %hdl settle !
#if-flag debug_wire
      ." Change Done timer " r@ %hdl state @ ~s .name cr
#endif
      r@ \mt
    else
#if-flag debug_wire
      ." Delay timer " r@ %hdl state @ ~s .name cr
#endif
." TTK " .s
      true r@ %hdl next_step
      r@ %hdl state @ ~s idle > if
." TTN " .s
        true r@ %hdl settle !
        ~t break 1+ r@ dup %hdl \set_timeout @ execute
      then
    then
." TTZ " .s
  again
;
;class

task subtask class: _t_reader
: \main
  task this checkarg @ >r
  begin
." TRA " .s
    r@ %hdl readq @
." IN:" dup %msg ?
    \ TODO do something with the thing
    %msg done
  again
;
;class

task subtask class: _t_written
\ task for finalizing sent messages
: \main
  task this checkarg @ >r
  begin
." TWA " .s
    r@ %hdl sentq @
." DONE: " dup %msg ?
    r@ %hdl sentq .. $30 dump
    %msg done
  again
;
;class



: setup ( hdl -- )
  \ 
  >r
  r@ __ writeq >setup
  r@ __ readq >setup
  r@ __ sentq >setup

  s" nbits" voc-eval  ( nbits )
  dup r@ __ wires !
  dup _mask r@ max !
  dup _len r@ __ len !
  dup _bits r@ __ bits !
  dup _n_end r@ __ n_end !
  r@ __ max @ r@ __ n_end @ exp 1- r@ __ val_end !
  1 r@ __ bits @ lshift r@ __ val_max !
  r@ __ len @ over 3 = if 1- then r@ __ len_crc !
  drop  ( - )

  s" get_wire" voc-xt  r@ __ \get_wire !
  s" set_wire" voc-xt  r@ __ \set_wire !
  s" set_state" voc-xt  r@ __ \set_state !
  s" set_timeout" voc-xt  r@ __ \set_timeout !
  s" timer_a" voc-eval r@ __ \timer_a !
  s" timer_b" voc-eval r@ __ \timer_b !
  8000 500 alloc mem add-if

  _t_timeout [mem-sz] mem alloc
  dup _t_timeout >setup
  r@ over _t_timeout checkarg !
  dup _t_timeout start
  r@ __ t_timeout !

  _t_written [mem-sz] mem alloc
  dup _t_written >setup
  r@ over _t_written checkarg !
  dup _t_written start
  r@ __ t_written !

  _t_reader [mem-sz] mem alloc
  dup _t_reader >setup
  r@ over _t_reader checkarg !
  dup _t_reader start
  r@ __ t_reader !

  ~s wait_idle r@ __ state !
  r@ __ reset
  ~t zero r@ dup __ \set_timeout @ execute
  rdrop
;



\
\     ****************
\     Public interface
\     ****************
\

: \wr >r
." WR H " .s
    r@ __ settle @ if
#if-flag debug_wire
      ." Change (Settle) " r@ state @ ~s .name cr
#endif
      dup r@ __ wire_settle
    else
#if-flag debug_wire
      ." Change (Delay) " r@ state @ ~s .name cr
#endif
      false r@ __ next_step
    then
." WR I " .s
    r@ dup __ \get_wire @ execute
." WR J " .s
    tuck =
." WR K " .s
  rdrop ;

: wire ( bits hdl -- )
\ wire status has changed
  >r
  begin
." WR A " .s
    dup 0= r@ __ last_zero !
    dup r@ __ current !
." WR C " .s
    r@ state @  ~s idle > if
." WR D " .s
      1 r@ __ flapping +!
      r@ __ flapping @  r@ __ wires @ 2* > if
." WR E " .s
        ~err FLAP r> __ error
." WR F " .s
        drop exit
      then
    then
." WR G " .s
    r@ \wr
  until
  drop
." WR W " .s
  r@ __ state @ ~s idle > if
." WR X " .s
    true r@ __ settle !
    ~t settle r@ dup __ \set_timeout @ execute
." WR Y " .s
  then
." WR Z " .s
  rdrop
;

: send ( msg hdl -- )
\ queue the message for sending
\ XXX TODO priority?
  tuck __ writeq !
  __ send_next
;

;class
