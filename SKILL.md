# TV Sorter

Scans `~/Downloads` for TV episode files (`.mkv`, `.avi`, `.mp4`), figures out
show + season + episode from the filename, confirms the show name against
TVmaze, and copies the file to:

```
/Storage/TV/<Show Name>/Season <NN>/SxxEyy.<ext>
```

## Rules

- Strip leading "The " and "A " from show names (per Jesse's preference).
- Preserve TVmaze's canonical casing when available; title-case otherwise.
- Scan **all** of `~/Downloads` recursively.
- Skip files modified within the last 15 minutes — they may still be
  downloading. They'll get picked up on a later run.
- **Move** the file (don't leave a copy behind — avoids repeating work daily).
- Skip + log if destination already exists; do not overwrite.
- Show name confirmed via TVmaze first, then Brave Search if TVmaze misses.
  If both fail, fall back to the parsed-from-filename name.
- Per-file try/except: one bad file never kills the whole run. Failures are
  collected in the report and surfaced to Jesse by the cron agent.
- Cache lookups in `~/.cache/tv-sorter/show-cache.json` (dict format).
- Log to `~/.cache/tv-sorter/sorter.log`, machine-readable report at
  `~/.cache/tv-sorter/last-run.json`.

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
