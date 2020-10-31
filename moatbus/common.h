#ifndef MOATBUS_COMMON
#define MOATBUS_COMMON

#define TRUE 1
#define FALSE 0

#ifndef DEBUG_WIRE
#define DEBUG_WIRE 0
#endif

#ifdef __cplusplus
#define IN_C extern "C"
#else
#define IN_C
#endif

#define NO_INIT __attribute__((__section__(".noinit")))

#endif
