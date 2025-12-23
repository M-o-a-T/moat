# Notes

## esp32

### esp32-c6

#### Gaggenau

The old version covers jtag/usb, pins 12+13.
To disable that, set fuse bits EFUSE\_DIS\_PAD\_JTAG and EFUSE\_DIS\_USB\_JTAG.
See manual, page 378.
