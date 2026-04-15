# Backup file save strategy

The MoaT-Link server records all changes to state in a series of files stored
under `link.server.save.dir`.  Two file types exist:

**Full files** (`mode: full` or `mode: init`)
  A snapshot of the entire data tree at the time of writing, followed by all
  subsequent changes up to the point where the file is closed.

**Incremental files** (`mode: incr`)
  Changes only, starting from the point in time where the previous file ended.
  An incremental file cannot be replayed on its own; it requires the preceding
  full file.

Files are named according to the `link.server.save.name` strftime pattern
(default `%Y-%m/%d/%H-%M.moat`) and rotated every `link.server.save.interval`
seconds.  Every `link.server.save.rewrite`-th file is a full snapshot; the
files in between are incremental.

## File format

Each file is a stream of CBOR records:

1. **Header** — `Tag(CBOR_TAG_CBOR_LEADER, Tag(CBOR_TAG_MOAT_FILE_ID, [description, meta]))`.
   `meta` is a mapping that includes at least `mode` (the file type) and
   `time` (the UTC datetime at which writing started).

2. **Data records** — one record per data node, each a
   `[depth, path, value, …meta]` list.

3. **Trailer** — `Tag(CBOR_TAG_MOAT_FILE_END, meta)` written when the file is
   closed normally.  `meta` may contain `mode: error` if the server crashed or
   was forcibly shut down while writing.

The four bytes `MeoF` (0x4D656F46) appear near the end of every complete file
as part of the CBOR-encoded trailer tag, making it straightforward to locate
the trailer by reading the last kilobyte of the file.

## Retention policy

The `link.server.save.keep` list controls which files are retained.  Cleanup
runs once at server startup (on the full set of existing files) and again after
each completed save cycle.

The algorithm maintains a position index `I` that starts at 0 (the newest
complete file) and advances through the file list (sorted newest-first).

For each entry in `keep`:

1. `I` is advanced past any incremental files at the current position, because
   incremental files are not useful without their preceding full file and are
   not counted by keep entries.

2. If the current file has `mode: error` in its trailer:

   - If `I < save.errors`: the error file is preserved and `I` advances past
     it without consuming the keep entry.
   - Otherwise the file is deleted.

3. The keep entry is applied:

   - **Integer N > 0** — advance `I` by `N`.  Files at indices `I..I+N-1`
     are skipped over (kept).

   - **Human-readable interval** (e.g. `"1 day"`, `"6 hours"`) — find the
     largest `X` such that
     `files[I].timestamp − files[I+X].timestamp ≤ interval`.
     All files strictly between `I` and `I+X` are deleted (the two
     endpoints are kept as the interval summary).  `I` advances by 1
     (unless `X = 0`, meaning no second file falls within the window).

After all keep entries are exhausted, every file with index greater than `I`
is deleted.

### Example

```yaml
save:
  errors: 10
  keep:
    - 10          # keep the 10 newest complete files verbatim
    - 1 day       # then one-per-day summary for the previous day
    - 10          # then 10 more files from the older archive
```

With this configuration the server keeps at most roughly 21 full files at any
time (plus any incremental files interleaved between them and up to 10 recent
error files).
