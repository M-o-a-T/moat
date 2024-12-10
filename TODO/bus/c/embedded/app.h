#ifndef _EMB_APP_H
#define _EMB_APP_H

#include "embedded/flash.h"

IN_C flash_start_proc start;
IN_C flash_process_proc process;
IN_C flash_loop_proc loop;
IN_C flash_stop_proc stop;

#endif
