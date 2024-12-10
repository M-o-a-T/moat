#include "moatbus/common.h"

IN_C void exit(int) __attribute__((section(".tetext")));
IN_C void exit(int) { for(;;) ; }
