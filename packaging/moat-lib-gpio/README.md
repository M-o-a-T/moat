# moat-lib-gpio

% start synopsis
% start main

MoaT-lib-GPIO allows easy access to the GPIO pins on your Raspberry Pi or
similar embedded computer.

% end synopsis

Testing MoaT-lib-GPIO requires a Linux distribution that enables the
mock-lib-GPIO module. As of mid-2020, Debian's kernel does not include this
module, but Raspbian's does.

% end main

If you can compile your own kernel: the option is named CONFIG\_GPIO\_MOCKUP,
in Device Drivers / GPIO support / Memory mapped GPIO drivers / GPIO
Testing Driver.

This code is based on libgpiod and its CFFI adapter by Steven P. Goldsmith
\<<mailto:sgjava@gmail.com>>, as downloaded from
[github](https://github.com/sgjava/userspaceio.git).

To run examples, make sure to install `trio` first.

Writing an actual test suite is TODO. There is a more elaborate test script
in [MoaT-KV-GPIO](https://github.com/smurfix/moat).
