#include <sys/types.h>
#include <stdarg.h>
#include <string.h>
#include <stdio.h>
#include <cstdlib>
#include <malloc.h>

#include "Arduino.h"
#include "stm32f1xx_hal_rcc.h"

#include "embedded/main.h"
#include "moatbus/message.h"
#include "moatbus/serial.h"
#include "moatbus/handler.h"

LOG logbuf;

uint16_t boot_count __attribute__((__section__(".noinit")));

extern "C" {
    void setup();
    void loop();
}

void check_boot_count()
{
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_PORRST))
        boot_count = 0;
    __HAL_RCC_CLEAR_RESET_FLAGS();
    ++boot_count;
}

static uint16_t mm;

void setup()
{
    setup_serial();
    logbuf = NULL;
    logger("Startup.");

    check_boot_count();
    setup_polled();
    mm=0;
}

extern "C" char *sbrk(int i);
unsigned int memspace()
{
    struct mallinfo mi = mallinfo();
    extern char _Min_Stack_Size;
    //extern char _end;
    //extern char _sdata;
    extern char _estack;

    //static char *ramstart = &_sdata;
    static char *ramend = &_estack;
    static char *minSP = (char*)(ramend - &_Min_Stack_Size);

    char *heapend = (char*)sbrk(0);
    char * stack_ptr = (char*)__get_MSP();
    return ((stack_ptr < minSP) ? stack_ptr : minSP) - heapend + mi.fordblks;
}

void loop()
{
    uint16_t m = millis();
    if(mm==0 || ((m-mm)&0xFFFF) >= 10000) {
        logger("* free: %d", memspace());
        mm=millis();
        if(!mm)
            mm = 1;
    }
    loop_serial();
    loop_polled();
}

void process_serial_msg(BusMessage msg, uint8_t prio)
{
#ifdef MOAT_REPEATER
    send_bus_msg(msg, prio);
#endif
}

char process_bus_msg(BusMessage msg)
{
    char res = 0;

    // XX TODO process this thing
#ifdef MOAT_REPEATER
    if(msg->dst == -4 || msg->dst == MOAT_REPEATER-4)
        res = 1;
    send_serial_msg(msg, 0);
    logger("Forward to serial: %s", msg_info(msg));
#endif
    return res;
}

void vlogger(const char * format, va_list arg)
{
    LOG *hdr = &logbuf;
    while(*hdr)
       hdr = &((*hdr)->next);
    uint8_t len = vsnprintf(NULL,0, format,arg);
    LOG buf = (LOG) malloc(sizeof(*logbuf)+len+2);
    vsnprintf(buf->buf, len+1, format, arg);
    buf->next = NULL;
    *hdr = buf;
}

void logger(const char *format, ...)
{
    va_list args;

    va_start(args, format);
    vlogger(format, args);
    va_end(args);
}
