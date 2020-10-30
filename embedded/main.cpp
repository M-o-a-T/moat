#include <sys/types.h>
#include <stdarg.h>
#include <string.h>
#include <stdio.h>
#include <cstdlib>

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

void loop()
{
    bool p = false;
    if(mm==0) {
        Serial.println("Z"); Serial.flush();
        mm=millis();
        p=true;
    }
    uint16_t m = millis();
    if(m-mm >= 1000) {
        Serial.println("L1"); Serial.flush();
        mm=m;
        p = true;
    }
    loop_serial();
    if(p) { Serial.println("L2"); Serial.flush(); }
    loop_polled();
    if(p) { Serial.println("L3"); Serial.flush(); }
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
