
\ Forth version of message

#require alloc lib/alloc.fs
#require class: lib/class.fs
#require var> lib/vars.fs

forth only definitions

forth definitions

#if defined moat
moat also
#else
voc: moat
#endif

#if defined msg
msg also
#else
voc: msg
#endif
moat ignore

#if moat msg defined mem
moat ignore
moat msg ignore
#end
#endif
moat ignore

: _mask ( bits -- n-1-bits )
  1 swap lshift 1-
;

: x-end
\ swap bytes
  dup 16 lshift swap 16 rshift or
  dup $ff00ff tuck and 8 lshift -rot
  bic 8 rshift or
;

alloc pool object: mem


\ A message consists of a series of bits, stored big-endian.
\
\ The message life-cycle is:
\
\ reading:
\ allocate
\ >recv
\ !b (chunks from the wire)
\ >read
\ reduce (re-allocate the buffer to free dead space)
\ @adr @adr @code (dst src code)
\ @ (read bytes) or @b drop (read bits)
\
\ writing:
\ allocate
\ >write
\ !adr !adr !code (dst src code)
\ ! (bytes) or !s (strings etc) or !b (bytes)
\ >send
\ @bf (read chunks for sending)
\

class: %msg
__data
    var> int  field: done  \ XT ( status msg -- )
    var> hint field: pos   \ offset, in bits
    var> cint field: prio  \ transmit priority
    var> cint field: len   \ bytes in this message
    aligned
    here: data
__seal



: max_len ( msg -- len )
\ max possible message length
  >alloc msize  0 __ data -
;

#if-flag debug
: len_chk ( bytes msg )
\ abort if @bytes won't fit
  __ len @ > abort" msg overrun"
;
#endif

: hdr_len ( msg -- hdr_len )
  __ data dup c@ $80 and if \ dst is server
    nip $10 and if 1 else 2 then
  else
    1+ c@ $80 and if 2 else 3 then
  then
;

: bit_len ( msg -- bits )
  __ len @ 3 lshift
;


: !b ( val frame-bits msg -- )
\ add bits to the message
  >r
#if-flag debug
  2dup _mask bic abort" ignored bits"
#endif
  r@ __ data r@ __ pos @ tuck 3 rshift +  ( val bits len adr )
  dup >r @ x-end ( val bits len oval |R: msg adr )
  swap dup >r $7 and ( val bits oval blen |R: msg adr len )
  32 swap - dup >r ( val bits oval boff |R: msg adr len boff )
  -1 swap lshift and ( val bits omval )
  -rot ( omval val bits )
  tuck r> ( omval bits val bits boff )
  swap - lshift rot or ( bits val |R: msg adr len )
  swap r> + ( val len' |R: msg adr )
  swap x-end r> !  ( len' |R: msg )
  r> __ pos !
;
  
: align ( msg -- )
\ go to the next byte boundary
  dup __ pos @ $7 and ?dup if
    8 swap - 0 swap rot __ !b
  else
    drop
  then
;


: @b ( bits msg -- data )
\ extract `frame_bits` bits from the message
  dup >r __ pos @  ( bits pos )
  2dup +
#if-flag debug
  dup r@ __ bit_len > abort" beyond end"
#endif
  r@ pos !
  dup $7 and swap 3 rshift r> __ data + ( fb bpos adr )
  @ x-end -rot ( val fb bpos )
  over swap + ( val fb fb-bpos )
  32 swap - rot swap rshift
  swap _mask and ( val' )
;


: @bf ( frame_bits msg -- flag data )
\ extract `frame_bits` bits from the message
\ the flag is true if this was the last chunk *and* the frame self-terminates the message
  over >r
  dup >r __ bit_len r@ __ pos @ -
#if-flag debug
  dup 0= abort" beyond end"
#endif
  ( fb xbits )
  2dup > if
    \ asked for more bits than are present. 
    tuck -
  else
    drop 0
  then ( fb xbit |R: fb msg )
  swap r@ __ pos @  ( xbit fb pos )
  2dup + r@ pos !
  dup $7 and swap 3 rshift r> __ data + ( xbit fb bpos adr |R: framebits )
  @ x-end -rot ( xbit val fb bpos )
  over swap + ( xbit val fb fb-bpos )
  32 swap - rot swap rshift
  swap _mask and ( xbit val' )

  swap ?dup if
    r> ( val xbit fb )
    over 8 >= if
      1 swap lshift -rot ( fbm val xbits )
      8 - lshift or
      true
    else
      drop lshift
      0
    then
  else
    rdrop
    0
  then
  swap
  ( flag data )
;


\ 
\ read
\
: >recv
\ prepare header for receiving
  dup __ max_len over __ len !
  0 swap __ pos !
;

#if 0
\ alternate char.wise impl, untested, copied from C, for reference
: !b ( val frame-bits msg -- )
  r@ swap >r __ pos @ ( val frame-bits bits |R> msg msg-end )
  begin over while
    dup 8 = if  \ on a byte boundary
      2dup < if \ less than 8 bits left?
        swap - ( val fb-b )
        tuck lshift r@ c! ( fb-b )
        0 0 rot
      else \ full byte, save it
        - (val fb-8 )
        2dup rshift r@ c!  r> 1+ >r
        8 \ still no claimed bits
      then
    else \ not on a boundary.
      2dup < if \ add a small chunk?
        dup _mask -rot ( val mask fb b )
        swap -  ( val mask b-fb )
        rot over lshift ( mask b-fb val< )
        rot and ( b data )
        r@ c@ or r@ c! ( b )
        0 0 rot
      else \ no, fill to boundary
        tuck - ( val bits fb-b )
        2 pick over rshift ( val bits fb val>fb)
        rot _mask and ( val fb val' )
        r@ c@ or r@ c!  r> 1+ >r
        8 \ no claimed bits now
      then
    then
  repeat
  r> r@ __ data - r@ __ len !
    r> __ pos !
    2drop
;
#endif


#if 0
: @end ( bits msg -- value )
\ chop bits off the end and return them
\ for CRC tests
\ transcribed from C code, untested
  dup >r __ bpos @ ( bits pos |R: msg )
  r@ __ data r@ __ end @ + >r ( bits pos |R: msg data_end )
  dup 8 < if
    2dup 8 swap - < if
      r> c@ swap rshift swap dup _mask and \ XXX wrong
      swap r@ __ pos @ swap r> __ pos !
      exit
    then
    r> c@ over rshift -rot ( res bits pos )
    8 swap - tuck -
  else
    drop
    0 0 rot
  then
  begin dup 8 >= while ( res shift bits |R> msg data_end )
    -rot ( bits res shift )
    r> 1- dup >r c@ over lshift rot or ( bits shift res )
    -rot 8 + swap 8 -
  repeat
  ?dup if
    dup 2r@ nip __ bpos !  \ save bits
    _mask
    r> 1- dup >r c@ and ( res shift data )
    swap lshift or
    over _mask 2 pick lshift 
  else
    drop
  then ( res )
  drop r> r@ __ data - r> __ len !
;
#endif

: >read ( msg -- )
\ prepare for extracting data
\ you might want to call REDUCE after this
  dup __ pos @ 3 rshift over __ len !
  0 swap __ pos !
;

: @ ( msg -- char )
\ get the next character
\ skips to the next byte boundary
  dup >r __ data r@ __ pos @
  7 + -8 and
  dup 8 + r@ __ pos !
  3 rshift
#if-flag debug
  dup r@ __ len @ >= abort" beyond end"
#endif
  + c@
  rdrop
;

: more?b ( msg -- bits )
\ tells how many bits are left in the message
  dup __ bit_len swap __ pos @ -
;

: more? ( msg -- bytes )
\ tells how many bytes are left in the message
  dup __ len @ swap __ pos @ 7 + 3 rshift -
;


: reduce ( msg -- msg' )
\ after receiving, realloc the message so that it requires less space
  dup __ len @ over __ max_len - 7 > if  \ or whatever
    dup __ len @  0 __ data +  dup >r  moat bus mem alloc  ( old new )
    2dup r> move
    swap moat bus mem free
  then
;

\
\ retrieve header data
\ 

: adr@ ( msg -- adr )
  1 over __ @b if \ server
    2 swap __ @b -4 or
  else
    7 swap __ @b
  then
;

: code@ ( msg -- code )
  8 over __ pos @ $7 and -
  swap __ @b
;
  
: hdr@ ( msg -- src dst code )
  dup >r adr@ r@ adr@ swap r> code@
;

\
\ write
\

: >write ( msg -- )
  dup __ max_len over __ len !
  0 swap __ pos !
;

: !adr ( adr msg -- )
  swap dup 0< if \ server
    $4 or $7 and 3 rot __ !b
  else \ client
#if-flag debug
    dup $80 >= abort" Adr too big"
#endif
    8 rot __ !b
  then
;
 
: !code ( code msg -- )
  8 over __ pos @ 7 and -  ( code msg bits )
#if-flag debug
  2 pick over _mask bic abort" Code too big"
#endif
  swap __ !b
;
  
: hdr! ( src dst code msg -- )
\ writes a message header and sets initial length
\ this calls >write
  dup >r __ >write
  -rot ( code src dst )
  r@ __ !adr \ save dst
  r@ __ !adr \ save src
  r> __ !code
;

: s! ( data len msg -- )
\ append data to the message
  dup align
  dup >r __ pos @ 3 rshift 
  ( data len pos )
  2dup +
#if-flag debug
  dup r@ __ len_chk
#endif
  3 lshift r@ __ pos !
  r> __ data + swap
  move
;

: s@ ( msg -- adr len )
\ return the current read/write pointer
  dup align
  dup >r __ data r@ __ pos @ 3 rshift ( adr pos )
  r> __ len @ over - ( adr pos rest )
  -rot + swap 
;

: pos+ ( len msg -- )
\ this number of bytes have been added/consumed
\ don't use this wen not aligned
#if-flag debug
  dup >r __ pos @ swap 3 lshift + r> __ len_chk
#endif
  swap 3 lshift swap __ pos +!
;

: ! ( byte msg -- )
\ append a byte to the message
  dup >r __ pos @ 7 + 3 rshift 
#if-flag debug
  dup 1+ r@ __ len_chk
#endif
  ( byte pos )
  tuck r@ __ data + c!
  1+ 3 lshift r> __ pos !
;

: >send ( msg -- )
\ prepare for sending
  dup __ pos @ 7 + 3 rshift over __ len !
  0 swap __ pos !
;


#if 0
\ alternate char.wise impl, untested, copied from C, for reference
: @b ( frame_bits msg -- data )
\ extract `frame_bits` bits from the message
  over >r
  dup >r __ bit_len r@ __ pos @ 3 lshift - 8 - r@ __ bpos @ +
  ( fb xbits )
  2dup > if
  else
  then ( fb xbit )
  r@ __ bpos @ swap
  r@ swap >r dup __ data swap __ pos @ + >r ( fb bits |R: frame_bits msg xbit data )
  0 -rot ( res fb bits )
  begin over while
    dup 8 = if
      2dup < if
        swap - ( res bits' )
        r@ c@ over rshift ( res bits val )
        rot or swap 0 swap
      else
        -
        r> dup 1+ >r c@ over lshift ( res fb val )
        rot or swap 8
      then
    else
      2dup < if
        tuck _mask ( res bits fb msk )
        -rot - ( res msk bits' )
        swap r@ c@ and ( res bits val )
        over rshift rot or ( bits res )
        swap ?dup 0= if
          r> 1+ >r
          8
        then ( res bits )
        0 swap ( res 0 bits )
      else
        tuck - swap ( res fb' bits )
        r> dup 1+ >r c@ ( res fb bits val )
        swap _mask and ( res fb val )
        over lshift ( res fb val< )
        rot or swap 8
      then
    then
  repeat
  nip ( res bits )
  r> r> swap r@ __ data - r@ __ pos !
  ( res bits xbits )
  swap r> __ bpos !
  ( res xbits )

  ?dup if
    r> ( res fb xbits )
    dup 8 >= if
      1 rot lshift -rot ( fbm res xbits )
      8 - lshift or
    else
      nip lshift
    then
  else
    rdrop
  then
  ( res )
;
#endif

\
\ end
\

: free ( msg -- )
\ free this message
  moat bus mem free 
;

: (free)  ( status msg -- )
\ XT for "done" to simply free the message
  __ free
  drop
;

: wake ( status msg -- )
\ if there's a done callback associated with the message, run it
  dup __ done @ .. ?dup if
    execute
  else
    2drop
  then
;

;class

: alloc ( maxsize -- msg )
  0 %msg data +
  moat bus mem alloc
;

#if-flag debug
#include ../moat-bus/utils/message.fs
#endif

\ SPDX-License-Identifier: GPL-3.0-only
#ok depth 0=
