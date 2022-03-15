#include <sys/types.h>

#include "moatbus/message.h"
#include "embedded/logger.h"
#include "embedded/app.h"

static u_int32_t m;
static u_int32_t mlim = 2;

bool start()
{
    logger("APP starting up");
    if(m) {
        logger("data not zeroed");
        return false;
    }
    if(mlim != 2) {
        logger("data not inited");
        return false;
    }
    return true;
}

// proess this message
bool process(BusMessage msg)
{
    logger("APP ignoring message %s", msg_info(msg));
    return false;
}

// idle loop hook
void loop()
{
    if(++m > mlim) {
        logger("APP idle");
        m = 0;
        mlim += mlim>>1;
    }
}

// must halt all interrupts, timers, and whatnot
void stop()
{
    logger("APP stop");
}


