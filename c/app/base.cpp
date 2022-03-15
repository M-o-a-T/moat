#include <memory.h>
#include "embedded/flash.h"
#include "embedded/app.h"

static flash_start_proc _start;
static flash_stop_proc _stop;

struct flash_hdr AppHeader __attribute__((__section__(".app_flash"))) {
    .magic = FLASH_MAGIC,
    .boot_crc = BOOT_CRC,
    .start = &_start,
    .process = &process,
    .loop = &loop,
    .stop = &_stop,
};

extern void (*__app_preinit_array_start []) (void) __attribute__((weak));
extern void (*__app_preinit_array_end []) (void) __attribute__((weak));
extern void (*__app_init_array_start []) (void) __attribute__((weak));
extern void (*__app_init_array_end []) (void) __attribute__((weak));
extern void (*__app_fini_array_start []) (void) __attribute__((weak));
extern void (*__app_fini_array_end []) (void) __attribute__((weak));

static void init_array() {
    size_t count, i;
    
    count = __app_preinit_array_end - __app_preinit_array_start;
    for (i = 0; i < count; i++)
        __app_preinit_array_start[i]();
    
    count = __app_init_array_end - __app_init_array_start;
    for (i = 0; i < count; i++)
        __app_init_array_start[i]();
}

static void fini_array() {
    size_t count, i;
    
    count = __app_fini_array_end - __app_fini_array_start;
    for (i = count - 1; i >= 0; i--)
        __app_fini_array_start[i]();
}

bool _start() {
    extern char _app_data_source;
    extern char _app_data_start;
    extern char _app_data_end;
    extern char _app_bss_start;
    extern char _app_bss_end;

    memcpy(&_app_data_start,&_app_data_source,&_app_data_end-&_app_data_start);
    memset(&_app_bss_start,0,&_app_bss_end-&_app_bss_start);
    init_array();
    return start();
}

void _stop() {
    stop();
    fini_array();
}

//IN_C bool _default_start() { return true; }
IN_C void _default_stop() { }
IN_C void _default_loop() { }
IN_C bool _default_process(BusMessage msg) { return false; }
//IN_C bool start() __attribute__((weak, alias("_default_start")));
IN_C void stop() __attribute__((weak, alias("_default_stop")));
IN_C void loop() __attribute__((weak, alias("_default_loop")));
IN_C bool process(BusMessage msg) __attribute__((weak, alias("_default_process")));

