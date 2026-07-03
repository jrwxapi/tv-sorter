#!/usr/bin/env bash
# Wrapper: single-instance lock + ensure log dir exists.
set -euo pipefail

LOCK="/tmp/tv-sorter.lock"
exec 9>"$LOCK"
if ! flock -n 9; then
  echo "tv-sorter already running; exiting" >&2
  exit 0
fi

cd "$(dirname "$0")"
exec python3 ./sort.py "$@"
