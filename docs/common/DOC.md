# MoaT documentation structure

## Relationships

### README

Each part of MoaT has a subdirectory `packaging/moat-…` with a README file.

A README must contain two inclusion markers:

* start/end synopsis

  The section between these markers is included in the main MoaT index.
  It should not contain headings.

* start/end main

  This section typically extends from the top of the file, after the
  level 1 heading. It ends before the non-informative parts (like license,
  contact, archive location). Short examples and other details which
  typically are in a README, but are documented in depth elsewhere,
  should also be excluded.

## Index

The index includes the synopsis parts of each MoaT part. It links to
that part's documentation.
