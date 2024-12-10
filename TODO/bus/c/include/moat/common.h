#ifndef MOATBUS_COMMON
#define MOATBUS_COMMON

#ifndef LOG_BUSMEM
#define LOG_BUSMEM 0
#endif

#ifndef DEBUG_WIRE
#define DEBUG_WIRE 0
#endif

#ifdef __cplusplus
#define IN_C extern "C"
#define TRUE true
#define FALSE false

#else
#define IN_C
#define TRUE 1
#define FALSE 0
typedef char bool;

#endif

#define NO_INIT __attribute__((__section__(".noinit")))

#endif
