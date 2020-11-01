#ifndef EMB_LOGGER_H
#define EMB_LOGGER_H

#include "moatbus/common.h"

// Logging.
IN_C void setup_logger();

// log something. Does not block.
IN_C void logger(const char* format, ...);
IN_C void vlogger(const char* format, va_list arg);

// get the first line in the log buffer
IN_C char* get_log_line();

// drop the first line
IN_C void drop_log_line();

#endif
