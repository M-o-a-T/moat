# Real-Time-Clock

## Outline

MoaT uses the RTC chip, if available, mainly for its memory. Some apps need to
remember transient state when they, or MoaT as a whole, is restarted. Other
state may need to be persisted to Flash so it's available on power loss. If
neither is an option, state recovery via the data link may be feasible.

## Data model

Items in RTC memory are indexed by simple strings (not paths).
The contents can be anything that's encodable by CBOR.

## Implementations

### RTC memory

Nonvolatile memory contains a CBOR-encoded dict, tagged with CBOR\_TAG\_CBOR\_FILEHEADER.

### File system

The file (set in ``cfg["dest"]``) contains a CBOR-encoded dict, optionally tagged with CBOR\_TAG\_CBOR\_FILEHEADER.

Some keys are special (set via cfg["direct"], a key→filename dict): the
associated value must be a string. It is written directly to that file.

### Link

`self.root.sub_at(self.cfg.path)` is called with one or two arguments (get / set).
