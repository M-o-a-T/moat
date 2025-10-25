// This configuration is for MoaT code on a BaguetteS3 prototyping board.

#define MICROPY_HW_BOARD_NAME               "MoaT BaguetteS3"
#define MICROPY_HW_MCU_NAME                 "ESP32S3"

// not needed
#define MICROPY_PY_MACHINE_I2S              (0)

// Enable UART REPL for modules that have an external USB-UART and don't use native USB.
#define MICROPY_HW_ENABLE_UART_REPL         (1)

// want BT here
#define MICROPY_PY_BLUETOOTH (1)
