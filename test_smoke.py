#!/usr/bin/env python3
"""End-to-end smoke test for tv-sorter.

Drives the real main() entrypoint against throwaway temp directories so that
runtime errors (e.g. a NameError raised inside iter_video_files) fail the test
instead of the nightly cron. Runs fully offline: the show-name cache is
pre-seeded, so no TVmaze/Brave network calls happen.

Run:
    python3 test_smoke.py          # or: python3 -m unittest test_smoke -v
"""

from __future__ import annotations

import json
import logging
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

import sort

# Filename whose parsed show name ("The Wire") we seed into the cache below.
SAMPLE = "The.Wire.S01E03.1080p.WEB.mkv"
SEED_CACHE = {"the wire": {"name": "Wire", "source": "seed"}}
EXPECTED_REL = Path("Wire") / "Season 01" / "S01E03.mkv"


class SmokeTest(unittest.TestCase):
    def setUp(self) -> None:
        # main() calls logging.basicConfig, which only takes effect once per
        # process. Reset handlers so each test reconfigures logging to its own
        # temp file (and old file handles get closed).
        for handler in logging.root.handlers[:]:
            handler.close()
            logging.root.removeHandler(handler)

        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        self.source = tmp / "downloads"
        self.dest = tmp / "library"
        self.source.mkdir()
        self.dest.mkdir()

        # Redirect every path the script writes to into the temp dir, and seed
        # the cache so canonical_show_name is a cache hit (no network).
        cache_dir = tmp / "cache"
        cache_dir.mkdir()
        sort.CACHE_DIR = cache_dir
        sort.CACHE_FILE = cache_dir / "show-cache.json"
        sort.LOG_FILE = cache_dir / "sorter.log"
        sort.REPORT_FILE = cache_dir / "last-run.json"
        sort.RUN_LOG = cache_dir / "runs.log"
        sort.MOVES_LOG = cache_dir / "moves.log"
        sort.CACHE_FILE.write_text(json.dumps(SEED_CACHE))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _make_video(self, name: str, *, age_seconds: int) -> Path:
        path = self.source / name
        path.write_bytes(b"not a real video")
        old = time.time() - age_seconds
        os.utime(path, (old, old))
        return path

    def _run(self, *extra: str) -> dict:
        argv = ["sort.py", "--source", str(self.source), "--dest", str(self.dest)]
        argv.extend(extra)
        old_argv = sys.argv
        sys.argv = argv
        try:
            rc = sort.main()
        finally:
            sys.argv = old_argv
        self.assertEqual(rc, 0, "main() should exit 0")
        report = json.loads(sort.REPORT_FILE.read_text())
        self.assertEqual(report["failures"], [], "no per-file failures expected")
        return report

    def test_dry_run_plans_without_moving(self) -> None:
        src = self._make_video(SAMPLE, age_seconds=3600)
        report = self._run("--dry-run")
        self.assertEqual(report["seen"], 1)
        self.assertEqual(report["moved"], 0)
        # Nothing actually moved.
        self.assertTrue(src.exists(), "source file must stay put on a dry run")
        self.assertFalse((self.dest / EXPECTED_REL).exists())

    def test_real_run_moves_and_logs(self) -> None:
        src = self._make_video(SAMPLE, age_seconds=3600)
        report = self._run()
        self.assertEqual(report["moved"], 1)
        self.assertFalse(src.exists(), "source file should be gone after move")
        self.assertTrue((self.dest / EXPECTED_REL).exists(),
                        f"expected episode at {EXPECTED_REL}")
        # The moves-only log recorded exactly this move.
        moves_log = sort.MOVES_LOG.read_text().strip().splitlines()
        self.assertEqual(len(moves_log), 1)
        self.assertIn(str(self.dest / EXPECTED_REL), moves_log[0])

    def test_recent_file_skipped(self) -> None:
        # Modified just now — treated as a possibly-still-downloading file.
        self._make_video(SAMPLE, age_seconds=60)
        report = self._run()
        self.assertEqual(report["seen"], 0, "in-flight download must be skipped")
        self.assertEqual(report["moved"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
