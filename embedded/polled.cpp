#include "Arduino.h"
#include "moatbus/common.h"
#include "moatbus/handler.h"
#include "embedded/main.h"
#include "embedded/timer.h"
#include "embedded/logger.h"

static uint16_t last_micros;
static uint16_t max_d;
#ifndef MOAT_T_A
#define MOAT_T_A 5000
#endif
#ifndef MOAT_T_B
#define MOAT_T_B (MOAT_T_A/5)
#endif

struct mtimer tm;

// set the timeout
static void moat_set_timeout(REF u_int16_t delay)
{
    if(DEBUG_WIRE)
        logger("SetTimeout %d %d",delay,micros());
    mtimer_cancel(&tm);
    if (delay == T_OFF)
        {}
    else if (delay == T_BREAK)
        mtimer_schedule(&tm, MT_USEC(MOAT_T_B));
    else
        mtimer_schedule(&tm, MT_USEC(MOAT_T_A) * (delay-T_BREAK));
}

static uint8_t last_bits;

// set the wire state
static void moat_set_wire(REF u_int8_t bits)
{
    uint8_t mods = last_bits ^ bits;
    if (!mods)
        return;

    if (mods & 1) {
        if (bits & 1) {
            pinMode(MOAT_WIRE_1, OUTPUT);
            digitalWrite(MOAT_WIRE_1, 0);
        } else {
            pinMode(MOAT_WIRE_1, INPUT);
        }
    }

    if (mods & 2) {
        if (bits & 2) {
            pinMode(MOAT_WIRE_2, OUTPUT);
            digitalWrite(MOAT_WIRE_2, 0);
        } else {
            pinMode(MOAT_WIRE_2, INPUT);
        }
    }
#if MOAT_WIRES > 2
    if (mods & 4) {
        if (bits & 4) {
            pinMode(MOAT_WIRE_3, OUTPUT);
            digitalWrite(MOAT_WIRE_3, 0);
        } else {
            pinMode(MOAT_WIRE_3, INPUT);
        }
    }
#endif

#if MOAT_WIRES > 3
    if (mods & 8) {
        if (bits & 8) {
            pinMode(MOAT_WIRE_4, OUTPUT);
            digitalWrite(MOAT_WIRE_4, 0);
        } else {
            pinMode(MOAT_WIRE_4, INPUT);
        }
    }
#endif

    last_bits = bits;
}

// get the wire state
static u_int8_t moat_get_wire(REF1)
{
    uint8_t ws = 0;
    if (!digitalRead(MOAT_WIRE_1))
        ws |= 1;
    if (!digitalRead(MOAT_WIRE_2))
        ws |= 2;
#ifdef MOAT_WIRE_3
    if (!digitalRead(MOAT_WIRE_3))
        ws |= 4;
#endif
#ifdef MOAT_WIRE_4
    if (!digitalRead(MOAT_WIRE_4))
        ws |= 8;
#endif
    return ws;
}

// process an incoming message. Return 1 if for us.
static char moat_process(REF BusMessage msg)
{
    logger("Got %s", msg_info(msg));
    return process_bus_msg(msg);
}

// signal that a message has been transmitted (or not)
static void moat_transmitted(REF BusMessage msg, enum HDL_RES result)
{
    logger("X:%d",result);
    msg_free(msg);
}

// print a debug message
static void moat_debug(REF const char *text, va_list arg)
{
    vlogger(text, arg);
}

// has a failure
static void moat_report_error(REF enum HDL_ERR err)
{
    logger("E:%d",err);
}


static struct BusCallbacks CB {
    set_timeout: moat_set_timeout,
    set_wire: moat_set_wire,
    get_wire: moat_get_wire,
    process: moat_process,
    transmitted: moat_transmitted,
    debug: moat_debug,
    report_error: moat_report_error,
};
static BusHandler BH;

static void run_timer() {
    hdl_timer(BH);
}

void setup_polled()
{
#if !defined(MOAT_WIRES) || MOAT_WIRES<2 || MOAT_WIRES>4
#error "MOAT_WIRES must be 2..4"
#endif 

#ifndef MOAT_WIRE_1
#error "You ned to define MOAT_WIRE_1 as a port alias"
#endif
    pinMode(MOAT_WIRE_1, INPUT);

#ifndef MOAT_WIRE_2
#error "You ned to define MOAT_WIRE_2 as a port alias"
#endif
    pinMode(MOAT_WIRE_1, INPUT);

#if MOAT_WIRES>2
#if !defined(MOAT_WIRE_3)
#error "You ned to define MOAT_WIRE_3 as a port alias"
#endif
    pinMode(MOAT_WIRE_3, INPUT);
#endif

#if MOAT_WIRES>3
#if !defined(MOAT_WIRE_4)
#error "You ned to define MOAT_WIRE_4 as a port alias"
#endif
    pinMode(MOAT_WIRE_4, INPUT);
#endif

    last_micros = micros();
    max_d = 0;
    last_bits = 0;

    BH = hdl_alloc(REFN MOAT_WIRES, &CB);
    mtimer_init(&tm,run_timer);
}

uint8_t last_reported = ~0;

void loop_polled()
{
    uint16_t m = micros();
    uint16_t d = m - last_micros;
    last_micros = m;
    if (max_d < d) {
        max_d = d;
        logger("DT %d",max_d);
    }

    uint8_t bits = moat_get_wire(REFN1);
    if (last_reported != bits) {
        hdl_wire(BH, bits);
        last_reported = bits;

        if(DEBUG_WIRE)
            logger("WIRE x%01x",bits);
    }
}

void send_bus_msg(BusMessage msg)
{
    logger("BusSend %s", msg_info(msg));
    hdl_send(BH, msg);
}

