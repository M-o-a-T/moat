#include <stdio.h>

#include "embedded/main.h"
#include "embedded/logger.h"

u_int16_t cpu_random(u_int16_t x)
{
    return x>>4;
}


void vlogger(const char * format, va_list arg)
{
    vprintf(format, arg);
}

void logger(const char *format, ...)
{
    va_list args;

    va_start(args, format);
    vlogger(format, args);
    va_end(args);
}

