Backup file save strategy
=========================

The MoaT-Link server records all changes in a history file.

In order for file restores to not be too much busy-work due to superseded
changes, the server frequently switches to a new savefile, using an
exponential backoff strategy.


