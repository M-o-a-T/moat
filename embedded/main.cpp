#include <sys/types.h>
#include <stdarg.h>
#include <string.h>
#include <stdio.h>
#include <cstdlib>
#include <malloc.h>

#include "Arduino.h"
#include "stm32f1xx_hal_rcc.h"
#include "usbd_desc_template.h"

#include "embedded/main.h"
#include "embedded/timer.h"
#include "embedded/logger.h"
#include "moatbus/message.h"
#include "moatbus/serial.h"
#include "moatbus/handler.h"
#include "embedded/client.h"

IN_C void setup();
IN_C void loop();

// external
#ifdef MOAT_REPEATER
void send_serial_msg(BusMessage msg, uint8_t prio);
#endif
void send_bus_msg(BusMessage msg, uint8_t prio);

uint16_t boot_count NO_INIT;
uint32_t cpu_random_seed NO_INIT;

void check_boot_count()
{
    if (__HAL_RCC_GET_FLAG(RCC_FLAG_PORRST))
        boot_count = 0;
    __HAL_RCC_CLEAR_RESET_FLAGS();
    ++boot_count;
}

struct mtick ten_seconds NO_INIT;

void ten_log()
{
    logger("* free: %d", memspace());
}

// STM32 only
#define U_ID1 0x1FFFF7E8
#define U_ID2 0x1FFFF7EC
#define U_ID3 0x1FFFF7F0

void setup()
{
    check_boot_count();
    cpu_random_seed = *(uint32_t *)U_ID1 ^ *(uint32_t *)U_ID2 ^ *(uint32_t *)U_ID3;
    setup_logger();
    setup_addr();
    setup_timer();
    setup_serial();
    logger("Startup, reboot#%d", boot_count);
    mtick_init(&ten_seconds, ten_log);
    mf_set(&ten_seconds.mf, 36); // that's ten seconds. Cf moatbus.util.py

    setup_polled();
    logger("Startup: free: %d", memspace());
    setup_get_addr();
}

IN_C char *sbrk(int i);

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
    mt_delay_t m = MT_READ();
    loop_timer(m);
    loop_serial();
    loop_polled();
}

#ifdef MOAT_REPEATER
void process_serial_msg(BusMessage msg, uint8_t prio)
{
    send_bus_msg(msg, prio);
}
#endif

void send_msg(BusMessage msg, char prio)
{
#ifdef MOAT_REPEATER
    if(msg->dst == -MOAT_REPEATER) {
        send_serial_msg(msg, 0);
        return;
    }
    if(msg->dst == -4)
        send_serial_msg(msg_copy(msg), 0);
#endif
    send_bus_msg(msg, prio);
}

char process_bus_msg(BusMessage msg)
{
    char res = 0;

    // XX TODO process this thing
#ifdef MOAT_REPEATER
    if(msg->dst == -4 || msg->dst == -MOAT_REPEATER)
        res = 1;
    send_serial_msg(msg, 0);
    logger("Forward to serial: %s", msg_info(msg));
    res = TRUE;
#else
    msg_free(msg);
#endif
    process_msg_in(msg);
    return res;
}

u_int8_t* cpu_serial()
{
    return (u_int8_t *)U_ID1;
}

u_int16_t cpu_random(u_int16_t max)
{
    return cpu_random_seed % max;
}

void setup_addr_done()
{
    // we have an address, do whatever else might be required
}

