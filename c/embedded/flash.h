#ifndef EMB_FLASH
#define EMB_FLASH

#include <sys/types.h>
#include "moatbus/common.h"
#include "moatbus/message.h"

// Flash writing. Results indicate success. Or not.

IN_C bool flash_erase(void *start, void *end);
IN_C bool flash_write(void *pos, u_int8_t *data, u_int16_t len);

extern bool flash_ok;

#define FLASH_MAGIC 0xF1A54C78

#define FLASH_BLOCK 64UL
struct flash_hdr;

// setup; true if OK
typedef bool (flash_start_proc)();

// process this message. DO NOT free it, the caller does that.
typedef bool (flash_process_proc)(BusMessage msg);

// idle loop. Called repeatedly, DO return from this as soon as possible.
typedef void (flash_loop_proc)();

// must halt all interrupts, timers, and whatnot
typedef void (flash_stop_proc)();

// Every flashed app must start with this header.
struct flash_hdr {
	u_int32_t magic;
	u_int32_t boot_crc;  // the boot code we're built for
	u_int32_t app_crc;  // this code

	u_int16_t ram_start;  // must be == boot's "_end" symbol, minus _start, 4-byte units
	u_int16_t ram_len;  // allocation for app's static memory, 4-byte units

	u_int16_t app_len;  // in FLASH_BLOCK blocks
	u_int16_t app_version;

	flash_start_proc *start;
	flash_process_proc *process;
	flash_loop_proc *loop;
	flash_stop_proc *stop;

	u_int8_t data[0];  // code
} __attribute__((packed));

IN_C char process_control_flash(BusMessage msg, u_int8_t *data, msglen_t len);
IN_C char process_app_msg(BusMessage msg);

// reserves memory for the application RAM. Must be called before any
// malloc() takes place.
IN_C void setup_flash();
IN_C void loop_flash();

#endif
