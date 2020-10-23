#ifndef MOATBUS_HANDLER
#define MOATBUS_HANDLER

/*
Bus handler for MoatBus

This interface mostly mimics handler.py
*/

#include <sys/types.h>
#include <stdarg.h>

#include "moatbus/message.h"

enum HDL_ERR {
    ERR_NOTHING = 1, // bus zero?
    ERR_COLLISION = -2, // will retry
    ERR_HOLDTIME = -11,
    ERR_ACQUIRE = -12,
    ERR_CRC = -13,
    ERR_BAD_COLLISION = -14,
    ERR_NO_CHANGE = -16, // bit flapping?
    ERR_FATAL = -20, // marker
    ERR_FLAP = -21, // too many changes, too little timeouts
    ERR_ACQUIRE_FATAL = -22, // this cannot happen unless the hardware is insane
    // code bugs
    ERR_UNUSED = -31,
    ERR_UNHANDLED = -32,
    ERR_CANNOT = -33,
};

#define T_OFF 0 // no timeout
#define T_BREAK 1 // writer: timer B, between wire check and next change
// anything greater is (n-T_BREAK)*timer A

/// Callbacks ///

// set the timeout
typedef void (cb_set_timeout)(void *ref, u_int16_t delay);

// set the wire state
typedef void (cb_set_wire)(void *ref, u_int8_t bits);

// get the wire state
typedef u_int8_t (cb_get_wire)(void *ref);

// process an incoming message
typedef char (cb_process)(void *ref, BusMessage msg);

// signal that a message has been transmitted (or not)
typedef void (cb_transmitted)(void *ref, BusMessage msg, enum HDL_RES result);

// print a debug message
typedef void (cb_debug)(void *ref, const char *text, va_list arg);

// has a failure
typedef void (cb_report_error)(void *ref, enum HDL_ERR err);

// the actual struct holding the callbacks
struct BusCallbacks {
    cb_set_timeout *set_timeout;
    cb_set_wire *set_wire;
    cb_get_wire *get_wire;
    cb_process *process;
    cb_transmitted *transmitted;
    cb_debug *debug;
    cb_report_error *report_error;
};

struct _BusHandler;
typedef struct _BusHandler *BusHandler;

// Allocate a new bus handler
BusHandler hdl_alloc(void *ref, u_int8_t n_wires, struct BusCallbacks *cb);

// Free a bus handler
void hdl_free(BusHandler hdl);

// Queue+send a message
void hdl_send(BusHandler hdl, BusMessage msg, char prio);

// Alert about current wire state
void hdl_wire(BusHandler hdl, u_int8_t bits);

// The timeout has triggered
void hdl_timer(BusHandler hdl);

#endif
