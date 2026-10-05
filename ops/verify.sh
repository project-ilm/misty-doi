#!/usr/bin/env bash
# ops/verify.sh: misty-doi's own gate. A payload with no gate is refused by the seeder.
# © 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI.
# SPDX-License-Identifier: GPL-3.0-or-later
set -uo pipefail
cd "$(dirname "$0")/.."
export PYTHONDONTWRITEBYTECODE=1
FAILS=0; UNJ=0; ROWS=()
chk() { local id="$1" name="$2"; shift 2; local out rc
  out="$("$@" 2>&1)"; rc=$?
  if [ $rc -eq 0 ]; then ROWS+=("  PASS     $id  $name")
  elif [ $rc -eq 3 ]; then ROWS+=("  UNJUDGED $id  $name: $(tail -1 <<<"$out")"); UNJ=$((UNJ+1))
  else ROWS+=("  FAIL     $id  $name"); FAILS=$((FAILS+1)); printf '%s\n' "$out" | tail -8 >&2; fi; }
m01() { python3 -c "import pytest" 2>/dev/null || { echo "pytest is not installed"; return 3; }
        PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q -p no:cacheprovider tests; }
m02() { command -v curl >/dev/null || { echo "curl is absent"; return 3; }
        WORKDIR="$PWD/.e2e-proof" bash e2e_misty.sh >/dev/null; local rc=$?; rm -rf .e2e-proof; return $rc; }
m03() { python3 tools/versions.py; }
m04() { ! find . -path ./.git -prune -o \( -name __pycache__ -o -name '*.pyc' -o -name '*.egg-info' \) -print | grep -q .; }
m05() { PYTHONPATH=. python3 -m misty.cli newversion --help | grep -q -- "--concept" \
        && PYTHONPATH=. python3 -m misty.cli update --help >/dev/null; }
chk M01 "the test suite passes, the version tests included"            m01
chk M02 "publish, newversion and walk prove out against the stand-in" m02
chk M03 "pyproject, __init__, misty.json and CITATION.cff agree"      m03
chk M04 "no build artefacts"                                          m04
chk M05 "the update features are on the command line"                 m05
echo "misty-doi: contract verification"; printf '%s\n' "${ROWS[@]}"
echo "  $((${#ROWS[@]} - FAILS - UNJ)) passed, $FAILS failed, $UNJ unjudged"
[ $FAILS -eq 0 ]
