# CalDAV calendar polling

% start synopsis
Polls CalDAV calendars and publishes alarm times to MoaT-Link.
% end synopsis

% start main

This module polls a CalDAV server for upcoming events and publishes the
next alarm time to a MoaT-Link destination path.  It replaces the legacy
``moat-kv-cal`` package.

## Quick start

1. Store your calendar configuration at a link path:

   ```shell
   moat link data set calendar.test url=https://cal.example/user user=me pass=secret zone=Europe/Berlin dst=.alarm.next
   ```

2. Run the alarm processor:

   ```shell
   moat link cal run test
   ```

3. List stored calendar data:

   ```shell
   moat link cal list
   ```

## Deprecation

This package supersedes ``moat-kv-cal``.  Calendar configuration now lives
in MoaT-Link under the ``calendar`` prefix.

% end main
