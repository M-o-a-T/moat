#include "moat/serial.h"
#include "moat/serial_msg.h"

#ifdef MOAT_SERIAL
static SerBus SB;
static  uint16_t last_m;
#endif

static char* log_wp;  // logbuf write pos

#define SER UART_DEV(0)

static void serial_rx(void *arg, uint8_t data) {
    sb_byte_in(SB, data);
    last_m = ztimer_now(ZTIMER_MSEC);
}

#ifndef MOAT_N_SERMSG
#define MOAT_N_SERMSG (16)
#endif
static mbox_t ser_mbox = {0};
static msg_t ser_msg_buf[MOAT_N_SERMSG]

static void send_serial_raw(const char *data, size_t len)
{
    uart_write(SER, data, len);
}

void setup_serial()
{
    uart_init(SER, 57600,serial_rx, NULL);
    send_serial_raw("INIT\n",5);

    log_wp = NULL;
#ifdef MOAT_SERIAL
    SB = sb_alloc();
    last_m = ztimer_now(ZTIMER_MSEC);
#endif
    mbox_init(&ser_mbox, ser_msg_buf, MOAT_N_SERMSG);
}

void loop_serial()
{
#ifdef MOAT_SERIAL
    uint16_t m = ztimer_now(ZTIMER_MSEC);
    if (last_m && ((m-last_m)&0xFFFF) > 100) {
        sb_idle(SB);
        last_m = m;
    }
    {
        BusMessage m = sb_recv(SB);
        if(m)
            process_serial_msg(m);
    }
#endif
}

void *msg_writer(void *arg)
{
       
    while (true) {
#ifdef MOAT_SERIAL
        while (SB->s_out != S_IDLE) {
            // prio to debug output. Drop clause 2 if you want prio to MoaT bus.
            int16_t ch = sb_byte_out(SB);
            if (ch >= 0) {
                Serial.write(ch);
                continue;
            }
        }
#endif
        msg_t m;
        mbox_get(&ser_mbox,&m, TRUE);
        if(m.value) {
            // text buffer
            send_serial_raw(m.ptr,strlen((char *)m.ptr);
            free(m.ptr);
        }
        if (log_wp == NULL) {
            log_wp = get_log_line();
            if(log_wp == NULL)
                break;
        }

        uint8_t ch = *log_wp++;
        while (ch) {
            Serial.write(ch);
            if(!low_mem)
                break;
            ch = *log_wp++;
        }
        if (ch)
            break;

        Serial.write('\n');
        if (low_mem)
            Serial.flush();
        drop_log_line();
        log_wp = NULL;
    }
}

void send_serial_str(const char *str)
{
    msg_t m;
    m.ptr = str;
    mbox_put(&ser_mbox,&m, TRUE);
}

#ifdef MOAT_SERIAL
void send_serial_msg(BusMessage msg)
{
    sb_send(SB, msg);
    msg_t m;
    m.value = 0;
    mbox_put(&ser_mbox,&m, TRUE);
}
#endif
