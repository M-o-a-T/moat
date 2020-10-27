#include "moatbus/serial.h"
#include "embedded/main.h"

#include "Arduino.h"

#ifdef MOAT_SERIAL
static SerBus SB;
static  uint16_t last_m;
#endif

static uint8_t log_wp;  // logbuf write pos

void setup_serial()
{
    Serial.begin(57600);
    log_wp = 0;
#ifdef MOAT_SERIAL
    last_m = millis();
#endif
}

void loop_serial()
{
#ifdef MOAT_SERIAL
    while(Serial.available()) {
        uint8_t ch = Serial.read();
        sb_byte_in(SB, ch);
    }
    {
        uint16_t m = millis();
        if (m-last_m > 100) {
            sb_idle(SB);
            last_m=m;
        }
    }
    {
        uint8_t p = 0;
        BusMessage m = sb_recv(SB, &p);
        if(m)
            process_serial_msg(m, p);
    }
#endif

    while (Serial.availableForWrite()) {
#ifdef MOAT_SERIAL
        if (SB->s_out != S_IDLE && SB->s_out != S_INIT) {
            // prio to debug output. Drop clause 2 if you want prio to MoaT bus.
            int16_t ch = sb_byte_out(SB);
            if (ch >= 0) {
                Serial.write(ch);
                continue;
            }
        }
#endif
        if (!logbuf)
            break;

        uint8_t ch = logbuf->buf[log_wp++];
        if (ch) {
            Serial.write(ch);
        } else {
            LOG lp = logbuf;
            logbuf = lp->next;
            free(lp);
            log_wp = 0;
        }
    }
}

#ifdef MOAT_SERIAL
void send_serial_msg(BusMessage msg, uint8_t prio)
{
    sb_send(SB, msg, prio);
}
#endif
