#!/usr/bin/env python3
"""TV Sorter — move TV episodes from ~/Downloads to /Storage/TV/<show>/Season XX/.

Behavior:
- Scan the source directory (default ~/Downloads) recursively.
- For each .mkv/.avi/.mp4 file, parse show + season + episode from filename.
- Confirm show name via TVmaze (free, no auth), with a Brave Search fallback.
- Strip leading "The "/"A " from show name (disable with --keep-articles).
- MOVE the file to <dest>/<Show>/Season NN/SxxEyy.<ext> (no duplicate work
  the next day).
- Per-file try/except: failures are isolated, collected, and printed at the end
  as JSON so a cron wrapper can forward them to you.

Configuration (CLI flag overrides env var overrides default):
    source    --source        TV_SORTER_SOURCE   default: ~/Downloads
    dest      --dest          TV_SORTER_DEST     default: /Storage/TV

Usage:
    sort.py            # do the work
    sort.py --dry-run  # plan only, do not move anything
    sort.py --verbose
    sort.py --source ~/Downloads --dest /mnt/media/TV
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

# Defaults. Override per-run with --source/--dest or the TV_SORTER_SOURCE /
# TV_SORTER_DEST environment variables (see resolve_paths()).
DEFAULT_SOURCE = Path(os.environ.get("TV_SORTER_SOURCE") or (Path.home() / "Downloads"))
DEFAULT_DEST = Path(os.environ.get("TV_SORTER_DEST") or "/Storage/TV")
VIDEO_EXTS = {".mkv", ".avi", ".mp4"}
# Ignore files touched within this window — they may still be downloading.
MIN_AGE_SECONDS = 15 * 60
CACHE_DIR = Path.home() / ".cache" / "tv-sorter"
CACHE_FILE = CACHE_DIR / "show-cache.json"
LOG_FILE = CACHE_DIR / "sorter.log"
REPORT_FILE = CACHE_DIR / "last-run.json"
RUN_LOG = CACHE_DIR / "runs.log"

TVMAZE_SINGLE = "https://api.tvmaze.com/singlesearch/shows?q={q}"
BRAVE_SEARCH = "https://api.search.brave.com/res/v1/web/search?q={q}&count=3"

SXXEYY = re.compile(r"[._\s-]?[sS](\d{1,2})[eE](\d{1,3})")

JUNK_TOKENS = {
    "720p", "1080p", "2160p", "480p", "4k",
    "webrip", "webdl", "web-dl", "web",
    "bluray", "blu-ray", "brrip", "bdrip",
    "hdtv", "hdrip", "dvdrip", "dvdscr",
    "x264", "x265", "h264", "h265", "hevc", "xvid", "divx",
    "aac", "ac3", "dts", "ddp5", "ddp", "atmos",
    "amzn", "nf", "hulu", "dsny", "atvp", "hmax",
    "repack", "proper", "internal", "limited", "extended",
    "complete", "season",
}


# ---------- I/O helpers ----------

def load_cache() -> dict:
    if CACHE_FILE.exists():
        try:
            return json.loads(CACHE_FILE.read_text())
        except Exception:
            return {}
    return {}


def save_cache(cache: dict) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    CACHE_FILE.write_text(json.dumps(cache, indent=2, sort_keys=True))


def setup_logging(verbose: bool) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    level = logging.DEBUG if verbose else logging.INFO
    handlers = [
        logging.FileHandler(LOG_FILE, encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ]
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=handlers,
    )


# ---------- Filename parsing ----------

def normalize_token(s: str) -> str:
    return re.sub(r"[._\-\s]+", " ", s).strip()


def parse_filename(name: str) -> tuple[str, int, int] | None:
    stem = Path(name).stem
    match = SXXEYY.search(stem)
    if not match:
        return None
    season = int(match.group(1))
    episode = int(match.group(2))
    head = stem[: match.start()]
    raw = normalize_token(head)
    parts = raw.split()
    cleaned: list[str] = []
    for part in parts:
        if part.lower() in JUNK_TOKENS:
            break
        cleaned.append(part)
    raw_show = " ".join(cleaned).strip()
    if not raw_show:
        return None
    return raw_show, season, episode


def strip_leading_article(name: str) -> str:
    return re.sub(r"^(?:the|a)\s+", "", name, flags=re.IGNORECASE).strip()


def sanitize_for_fs(name: str) -> str:
    # Remove all punctuation from folder names EXCEPT hyphens (which don't
    # complicate shell scripting), then collapse any whitespace the removal
    # left behind (e.g. "Law & Order" -> "Law Order").
    no_punct = re.sub(r"[^\w\s-]|_", "", name)
    return re.sub(r"\s+", " ", no_punct).strip()


# ---------- Show-name confirmation ----------

def tvmaze_lookup(query: str) -> str | None:
    url = TVMAZE_SINGLE.format(q=urllib.parse.quote(query))
    try:
        with urllib.request.urlopen(url, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        return data.get("name")
    except Exception as exc:
        logging.debug("TVmaze miss for %r: %s", query, exc)
        return None


def brave_lookup(query: str) -> str | None:
    """Cheap existence check via Brave Search. Returns first plausible title."""
    api_key = os.environ.get("BRAVE_API_KEY")
    if not api_key:
        logging.debug("BRAVE_API_KEY not set; skipping Brave fallback")
        return None
    url = BRAVE_SEARCH.format(q=urllib.parse.quote(f"{query} tv show"))
    req = urllib.request.Request(
        url,
        headers={
            "Accept": "application/json",
            "X-Subscription-Token": api_key,
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        results = (data.get("web") or {}).get("results") or []
        if not results:
            return None
        # First result title often contains the canonical show name.
        # We're only using this to confirm the show "exists" — keep raw query.
        logging.debug("Brave first result: %s", results[0].get("title"))
        return query  # accept the parsed name as-is if Brave found anything
    except Exception as exc:
        logging.debug("Brave miss for %r: %s", query, exc)
        return None


def canonical_show_name(raw_show: str, cache: dict, keep_articles: bool = False) -> tuple[str, str]:
    """Return (folder_name, source)."""
    key = raw_show.lower()
    cached = cache.get(key)
    if isinstance(cached, dict) and cached.get("name"):
        return cached["name"], cached.get("source", "cache")
    # Legacy cache entries were plain strings; ignore and refresh.

    name = tvmaze_lookup(raw_show)
    source = "tvmaze"
    if not name:
        name = brave_lookup(raw_show)
        source = "brave" if name else "raw"
    if not name:
        name = raw_show.title()

    if not keep_articles:
        name = strip_leading_article(name)
    folder = sanitize_for_fs(name)
    cache[key] = {"name": folder, "source": source}
    save_cache(cache)
    time.sleep(0.2)
    return folder, source


# ---------- Filesystem ----------

def iter_video_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if path.suffix.lower() not in VIDEO_EXTS:
            continue
        # Skip hidden / partial download files.
        if path.name.startswith("."):
            continue
        if path.name.endswith(".part"):
            continue
        # Skip files still being written — give downloads time to settle.
        try:
            age = time.time() - path.stat().st_mtime
        except OSError:
            continue
        if age < MIN_AGE_SECONDS:
            logging.info(
                "Skip (modified %.0fs ago, may still be downloading): %s",
                age, path.name,
            )
            continue
        yield path


def move_file(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    # shutil.move handles cross-filesystem renames (Downloads → /Storage).
    shutil.move(str(src), str(dest))


def plan_destination(
    src: Path, cache: dict, dest_root: Path, keep_articles: bool = False
) -> tuple[Path, str] | None:
    parsed = parse_filename(src.name)
    if not parsed:
        return None
    raw_show, season, episode = parsed
    show, source = canonical_show_name(raw_show, cache, keep_articles)
    if not show:
        return None
    ext = src.suffix.lower()
    dest_dir = dest_root / show / f"Season {season:02d}"
    dest = dest_dir / f"S{season:02d}E{episode:02d}{ext}"
    return dest, source


# ---------- Main ----------

def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="plan only; move nothing")
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--source", type=Path, default=DEFAULT_SOURCE,
                        help=f"directory to scan (env TV_SORTER_SOURCE; default {DEFAULT_SOURCE})")
    parser.add_argument("--dest", type=Path, default=DEFAULT_DEST,
                        help=f"TV library root (env TV_SORTER_DEST; default {DEFAULT_DEST})")
    parser.add_argument("--keep-articles", action="store_true",
                        help='keep leading "The "/"A " in show folder names')
    args = parser.parse_args()

    setup_logging(args.verbose)
    logging.info(
        "TV sorter starting (source=%s, dest=%s, dry_run=%s)",
        args.source, args.dest, args.dry_run,
    )

    if not args.source.exists():
        logging.error("Source directory missing: %s", args.source)
        return 2
    if not args.dest.exists():
        logging.error(
            "Destination root missing: %s "
            "(set --dest or TV_SORTER_DEST to your TV library root)",
            args.dest,
        )
        return 2

    cache = load_cache()
    seen = moved = skipped_unknown = skipped_exists = 0
    failures: list[dict] = []
    moves: list[dict] = []

    for src in iter_video_files(args.source):
        seen += 1
        try:
            plan = plan_destination(src, cache, args.dest, args.keep_articles)
            if plan is None:
                logging.info("Skip (no SxxEyy or unknown show): %s", src.name)
                skipped_unknown += 1
                continue
            dest, source = plan
            if dest.exists():
                logging.info("Exists at dest, skip: %s", dest)
                skipped_exists += 1
                continue
            logging.info("Plan [%s]: %s  ->  %s", source, src, dest)
            if args.dry_run:
                continue
            move_file(src, dest)
            moved += 1
            moves.append({"src": str(src), "dest": str(dest), "source": source})
            logging.info("Moved: %s", dest)
        except Exception as exc:
            logging.exception("Failed on %s: %s", src, exc)
            failures.append({"file": str(src), "error": f"{type(exc).__name__}: {exc}"})
            continue

    report = {
        "ts": int(time.time()),
        "dry_run": args.dry_run,
        "seen": seen,
        "moved": moved,
        "skipped_exists": skipped_exists,
        "skipped_unknown": skipped_unknown,
        "failures": failures,
        "moves": moves,
    }
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    REPORT_FILE.write_text(json.dumps(report, indent=2))

    # Append a compact run log for cron debugging / history (one line per run)
    try:
        with open(RUN_LOG, "a", encoding="utf-8") as f:
            ts_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(report["ts"]))
            f.write(
                f"{ts_str} seen={seen} moved={moved} already={skipped_exists} "
                f"unrecognized={skipped_unknown} failures={len(failures)}\n"
            )
    except Exception as log_exc:
        logging.warning("Failed to append runs.log: %s", log_exc)

    logging.info(
        "Done. seen=%d moved=%d already=%d unrecognized=%d failures=%d",
        seen, moved, skipped_exists, skipped_unknown, len(failures),
    )
    # Emit JSON summary on stdout for the wrapper / cron agent to parse.
    print("---REPORT-JSON---")
    print(json.dumps(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
