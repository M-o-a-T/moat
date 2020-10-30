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
    Serial.print("INIT\n");
    Serial.flush();

    log_wp = 0;
#ifdef MOAT_SERIAL
    SB = sb_alloc();
    last_m = millis();
#endif
}

void loop_serial()
{
#ifdef MOAT_SERIAL
    while(Serial.available()) {
        Serial.println("C1"); Serial.flush();
        uint8_t ch = Serial.read();
        sb_byte_in(SB, ch);
        Serial.println("C2"); Serial.flush();
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
        if(m) {
            Serial.println("C6"); Serial.flush();
            process_serial_msg(m, p);
            Serial.println("C7"); Serial.flush();
        }
    }
#endif

    while (Serial.availableForWrite()) {
#ifdef MOAT_SERIAL
        if (SB->s_out != S_IDLE && SB->s_out != S_INIT) {
            Serial.println("C9"); Serial.flush();
            // prio to debug output. Drop clause 2 if you want prio to MoaT bus.
            int16_t ch = sb_byte_out(SB);
            if (ch >= 0) {
                Serial.write(ch);
                continue;
            }
            Serial.println("C10"); Serial.flush();
        }
#endif
        if (!logbuf) {
            break;
        }

        uint8_t ch = logbuf->buf[log_wp++];
        while (ch) {
            Serial.write(ch);
            // break;
            ch = logbuf->buf[log_wp++];
        }
        if (ch)
            continue;
        Serial.write('\n'); Serial.flush();
        LOG lp = logbuf;
        logbuf = lp->next;
        free(lp);
        log_wp = 0;
    }
}

#ifdef MOAT_SERIAL
void send_serial_msg(BusMessage msg, uint8_t prio)
{
    sb_send(SB, msg, prio);
}
#endif
