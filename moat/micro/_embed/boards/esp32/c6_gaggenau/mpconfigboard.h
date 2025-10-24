// This configuration is for the MoaT replacement board for older Gaggenau kitchen vents.

#define MICROPY_HW_BOARD_NAME               "MoaT Herd"
#define MICROPY_HW_MCU_NAME                 "ESP32C6"

#define MICROPY_PY_MACHINE_I2S              (0)

// Enable UART REPL for modules that have an external USB-UART and don't use native USB.
#define MICROPY_HW_ENABLE_UART_REPL         (1)

// turn off USB and JTAG. Don't need them, used the pins (admittedly by mistake).
#define MICROPY_HW_ESP_USB_SERIAL_JTAG      (0)

// don't need BT here
#define MICROPY_PY_BLUETOOTH (0)
#define MICROPY_PY_BLUETOOTH_NIMBLE (0)
