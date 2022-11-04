# MoaT Modbus device registry

This archive collects modbus register descriptions for a many devices as
possible.

## Organization

Devices types are collected in subdirectories (e.g. `energy_meter`). Each
device is described by a YAML file.

The "include" key contains a list of other device description files to
include. Later values supersede earlier ones.

The "regs" key contains a hierarchy of register descriptions. 

The "dev" key describes the device.

## Register Hierarchy

## Data Types

Terminal objects use the following keys:

* register

  The register to access. Zero-based. Use `regtype` instead of a leading
  digit.

* regtype

  The register's type. The default is `i` for (numeric) Input. Use `h` for
  a Holding register, `c` for Coils (i.e. binary output), and `d` for
  Discrete (binary) inputs.

* type

  The type of the value in this register. Numbers use `int` or `float`. You
  may prefix these with

  * s (word-swapped: low word first)

  * u (unsigned; not used for `float`)

  (in this order), and/or append

  * 1 or 16 (one word: 16 bits; the default for `int`)

  * 2 or 32 (two words: 32 bits; the default for `float`)

  * 4 or 64 (four words: 64 bits)

  The types `str` and `bin` require a length. Strings can be
  zero-terminated. For these types, the initial `s` designates
  byte-swapping.

  Binary registers don't have a type, but you can use `i` for inverting the
  value. Use `u` if you need to un-invert a register.

* unit

  The unit of measurement. Use SI units only please, except for absolute degrees
  Celsius (expressed as "dC"). Factors like `k` for 1000 are specified with
  "scale".

* scale

  The scale for the measurement, as a power of 10. Thus `kW` uses factor 3,
  100th of an ampere uses factor -2. The default is zero.

  A trailing `b` indicates powers of two instead.

  Use a factor if the scale is not an integer.

* factor

  A correction factor that should be added to the measurement. Applied in
  addition to the scale. The default is 1.

* offset

  An offset that should be added to the measurement. Applied after
  scale+factor. The default is zero.

* scale\_reg

  Dynamic scaling (i.e. the scale is configured / auto-adjusted, available in a
  different register). Read this register and add it to "scale".

  The default is fixed scaling, designated by `-1`.

* scale\_regtype

  As `regtype` but for the scaling register.

* scale\_type

  `l` for logarithmic, `f` for a factor.

* value

  For objects used to identify device types, the register's value is
  contained in this entry. This can be either an integer or a list.


Objects may not overlap.
