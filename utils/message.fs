forth only definitions

#if undefined u.0
: u.0 ( u -- ) 0 <# #S #> type ;
#endif

moat bus also
%msg definitions
: ? ( msg -- )
  dup __ prio @ ?dup if ." Prio:" . then
  dup __ pos @ dup 3 rshift ." Pos:" u.0 
  7 and ?dup if [char] + emit u.0 then
  space
  dup __ len @ ." Len:" .
  dup __ max_len ." Max:" .
  dup __ data swap __ max_len dump8
;

forth definitions only
