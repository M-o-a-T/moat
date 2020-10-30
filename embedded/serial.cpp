#include "moatbus/serial.h"
#include "embedded/main.h"

#include "Arduino.h"

#ifdef MOAT_SERIAL
static SerBus SB;
static  uint16_t last_m;
#endif

static uint8_t log_wp;  // logbuf write pos
static uint16_t g_low_mem;

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
    g_low_mem = 0;
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
            process_serial_msg(m, p);
        }
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
        // The idea behind this code: if we're low on memory we write the
        // whole buffer synchronously so that the log buffer gets freed
        bool low_mem = (memspace() < 1000);

        if(g_low_mem && !low_mem && ((millis()-g_low_mem)&0xFFFF) > 1000) {
            g_low_mem = 0;
            logger("\n* Memory OK *");
        } else if(low_mem && g_low_mem == 0) {
            g_low_mem = millis();
            if (!g_low_mem)
            g_low_mem = 1;
            Serial.println("\n* Memory full *");
        }
        if (!logbuf) {
            break;
        }

        uint8_t ch = logbuf->buf[log_wp++];
        while (ch) {
            Serial.write(ch);
            if(!low_mem)
                break;
            ch = logbuf->buf[log_wp++];
        }
        if (ch)
            continue;

        Serial.write('\n');
        if (low_mem)
            Serial.flush();
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
