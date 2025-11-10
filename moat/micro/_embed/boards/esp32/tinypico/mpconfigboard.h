#ifndef MICROPY_HW_BOARD_NAME
// Can be set by mpconfigboard.cmake.
#define MICROPY_HW_BOARD_NAME               "MoaT TinyPico"
#endif
#define MICROPY_HW_MCU_NAME                 "ESP32"

// Enable UART REPL for modules that have an external USB-UART and don't use native USB.
#define MICROPY_HW_ENABLE_UART_REPL         (1)

#define MICROPY_HW_I2C0_SCL                 (22)
#define MICROPY_HW_I2C0_SDA                 (21)
