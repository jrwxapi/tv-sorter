# tv-sorter

Scans a downloads directory for TV episode files (`.mkv`, `.avi`, `.mp4`),
works out the show, season, and episode from each filename, confirms the show
name against [TVmaze](https://www.tvmaze.com/api), and **moves** the file into a
tidy library:

```
<dest>/<Show Name>/Season <NN>/SxxEyy.<ext>
```

For example, `The.Office.US.S02E05.1080p.WEB.mkv` becomes
`Office/Season 02/S02E05.mkv`.

## What it does

- Scans the source directory **recursively**.
- Parses `SxxEyy` (or `sXXeYY`) out of the filename and strips release junk
  (`1080p`, `WEB-DL`, `x265`, group tags, …) to recover the show name.
- Confirms the show name against TVmaze, preserving its canonical casing. Falls
  back to Brave Search (if `BRAVE_API_KEY` is set), then to the parsed name.
- Strips a leading `The `/`A ` from the folder name (disable with
  `--keep-articles`).
- Skips files modified in the last 15 minutes — they may still be downloading.
- Skips (never overwrites) a file that already exists at the destination.
- Isolates per-file errors so one bad file can't kill the run; failures are
  collected into the run report.
- Caches show-name lookups so repeat runs don't re-hit the network.

## Setup

**Prerequisites:** Python 3.8+ (standard library only — no `pip install`).

**Destination:** point the tool at your TV library root. It refuses to run if
the destination doesn't exist. Set it per-run with `--dest`, or once via an
environment variable:

```bash
export TV_SORTER_SOURCE="$HOME/Downloads"   # default: ~/Downloads
export TV_SORTER_DEST="/mnt/media/TV"       # default: /Storage/TV
```

**Optional:** `export BRAVE_API_KEY=...` to enable the Brave Search fallback for
shows TVmaze can't find.

## Usage

```bash
./sort.py --dry-run                          # preview every move, touches nothing
./sort.py                                     # the real thing
./sort.py --source ~/Downloads --dest /mnt/media/TV
./sort.py --keep-articles                     # keep "The "/"A " in folder names
./sort.py --verbose                           # debug logging
```

CLI flags override environment variables, which override the built-in defaults.

`run.sh` is a thin wrapper that adds a single-instance lock (`flock`) so
overlapping cron runs can't collide — use it for scheduled runs:

```bash
./run.sh --dry-run
```

## Logs and reports

Written under `~/.cache/tv-sorter/`:

- `sorter.log` — full log.
- `runs.log` — one compact line per run (counts) for history.
- `last-run.json` — machine-readable report of the most recent run. The same
  JSON is printed to stdout after a `---REPORT-JSON---` marker so a cron agent
  can parse it.

## Scheduling

Any scheduler works. A daily cron entry, for example:

```cron
30 17 * * *  TV_SORTER_DEST=/mnt/media/TV /path/to/tv-sorter/run.sh >> ~/.cache/tv-sorter/cron.out 2>&1
```
