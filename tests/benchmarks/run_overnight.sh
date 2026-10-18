#!/usr/bin/env bash
# Run the whole benchmark matrix unattended on a quiet machine.
#
#   tests/benchmarks/run_overnight.sh <fork-venv-python> <mainline-venv-python> <results-dir>
#
# Keeps the Mac from idle-sleeping while it runs (the lid must stay open or
# an external display attached), logs to <results-dir>/driver.log, and writes
# <results-dir>/DONE when finished. Safe to rerun: finished stores are skipped.
set -uo pipefail
FORK=${1:?fork venv python}
MAIN=${2:?mainline venv python}
OUT=${3:?results dir}
HERE="$(cd "$(dirname "$0")" && pwd)"
mkdir -p "$OUT"
rm -f "$OUT/DONE"
{
  echo "start $(date '+%Y-%m-%d %H:%M:%S')"
  caffeinate -i -s python3 "$HERE/driver.py" --fork-python "$FORK" --mainline-python "$MAIN" --out "$OUT" --runs 5 --concurrent-runs 3
  caffeinate -i -s python3 "$HERE/driver.py" --django --fork-python "$FORK" --mainline-python "$MAIN" --out "$OUT" --django-runs 3
  echo "end $(date '+%Y-%m-%d %H:%M:%S')"
} >> "$OUT/driver.log" 2>&1
touch "$OUT/DONE"
