# MoaT Modbus device registry

This archive collects modbus register descriptions for a many devices as
possible.

## Organization

Devices types are collected in subdirectories (e.g. `energy_meter`). Each
device is described by a YAML file.

The "include" key contains a list of other device description files to
include. Later values supersede earlier ones.

The "regs" key contains a hierarchy of register descriptions. 

## Data Types


Terminal objects use the following keys:

* register

  The register to access.

* regtype

  The register type. The default is `i` for Input. Use `h` for a Holding
  register.

* type

  The value type. Known values are `int`, `uint` and `float`. You may
  prefix these with

  * s (word-swapped, low word first)

  * u (unsigned, not for `float`)

  and postfix them with

  * 2 or 32 (two words)

  * 4 or 64 (four words)

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

  The default is fixed scaling.

* scale\_regtype

  As `regtype` but for the scaling register.

* scale\_type

  `l` for logarithmic, `f` for a factor.

