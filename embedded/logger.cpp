#include "embedded/logger.h"

#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>

typedef struct _log {
    struct _log *next;
    char buf[0];
} *LOG;

static LOG logbuf NO_INIT;

void setup_logger() {
    logbuf = NULL;
}

char* vlogger(const char * format, va_list arg)
{
    LOG* hdr = &logbuf;
    while(*hdr)
       hdr = &((*hdr)->next);
    uint8_t len = vsnprintf(NULL,0, format,arg);
    LOG buf = (LOG) malloc(sizeof(*logbuf)+len+1);
    vsnprintf(buf->buf, len+1, format, arg);
    buf->next = NULL;
    *hdr = buf;
    return buf->buf;
}

char* logger(const char *format, ...)
{
    va_list args;
    char* res;

    va_start(args, format);
    res = vlogger(format, args);
    va_end(args);
    return res;
}

char* get_log_line()
{
    if(!logbuf)
        return NULL;
    return logbuf->buf;
}

void drop_log_line()
{
    if(!logbuf)
        return;

    LOG lp = logbuf;
    logbuf = lp->next;
    free(lp);
}


