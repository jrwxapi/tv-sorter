# TV Sorter

_Version 1.1.0_

Scans `~/Downloads` for TV episode files (`.mkv`, `.avi`, `.mp4`), figures out
show + season + episode from the filename, confirms the show name against
TVmaze, and copies the file to:

```
/Storage/TV/<Show Name>/Season <NN>/SxxEyy.<ext>
```

## Rules

- Strip leading "The " and "A " from show names (per Jesse's preference).
- **Always Title Case** the folder name, regardless of source (TVmaze, Brave,
  or filename fallback). Case-sensitive Linux otherwise ends up with both
  "Line of Duty" and "Line Of Duty" as separate folders. Apostrophe-safe.
- **Drop a trailing release year** from the show name ("Line of Duty 2012" ->
  "Line of Duty"). We rely on TVmaze picking one canonical show per name, so a
  year in the folder is redundant. Caveat: if two genuinely different series
  share the exact same name (e.g. a remake), they'd collapse into one folder —
  accepted tradeoff; revisit only if that actually happens.
- Scan **all** of `~/Downloads` recursively.
- Skip files modified within the last 15 minutes — they may still be
  downloading. They'll get picked up on a later run.
- Never scan the destination library as input: skip symlinks and anything that
  resolves under `/Storage/TV`, and never overwrite an existing destination
  file. Guards against re-sorting already-filed episodes.
- **Move** the file (don't leave a copy behind — avoids repeating work daily).
- Skip + log if destination already exists; do not overwrite.
- Show name confirmed via TVmaze first, then Brave Search if TVmaze misses.
  If both fail, fall back to the parsed-from-filename name.
- Per-file try/except: one bad file never kills the whole run. Failures are
  collected in the report and surfaced to Jesse by the cron agent.
- Cache lookups in `~/.cache/tv-sorter/show-cache.json` (dict format).
- Verbose per-run logging goes to `~/.cache/tv-sorter/sorter.log`; the
  machine-readable report is `~/.cache/tv-sorter/last-run.json`.
- **Moves-only log** at `~/.cache/tv-sorter/moves.log` — one tab-separated line
  (`timestamp  src  dest`) per completed move, nothing else. This is the quiet
  log to consult when you just want to know what actually moved.

## Files

- `sort.py` — the worker script.
- `run.sh` — wrapper that handles logging + lockfile.

## Scheduling

Runs daily at 17:30 PT via OpenClaw cron (job: `tv-sorter-daily`).

Manual run:

```bash
python3 ~/Projects/skills/tv-sorter/sort.py --dry-run
python3 ~/Projects/skills/tv-sorter/sort.py
```
