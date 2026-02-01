# The Simple Data protocol

Several subsystems in MoaT-Link and -Micro support a "simple data" command.

* A single positional item writes

* `NotGiven` deletes

* No positional data: read

More than one positional argument is an error. Keyword args tend to be ignored.
The destination is a `d_` command, or may be the object itself if that is
unambiguous.
