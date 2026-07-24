#!/usr/bin/env bash
# Proves, by running them: publish mints a concept; newversion keeps that concept
# and adds a version beneath it; inherited files are cleared; and walk detects the
# split-lineage damage that publish-instead-of-newversion causes.
#
# Live Zenodo is never contacted. See mock_zenodo.py for why.
set -euo pipefail
# Locate the package whether this script sits beside it (a source checkout) or
# inside the repository itself (after apply).
HERE="$(cd "$(dirname "$0")" && pwd)"
if   [ -d "$HERE/misty" ];               then PKG="$HERE"
elif [ -d "$HERE/misty-doi-main/misty" ]; then PKG="$HERE/misty-doi-main"
else echo "cannot find the misty package next to $HERE" >&2; exit 2; fi
cd "$PKG"

PORT="${PORT:-0}"
if [ "$PORT" = "0" ]; then
  PORT=$(python3 -c "
import socket
s=socket.socket(); s.bind((\"127.0.0.1\",0)); print(s.getsockname()[1]); s.close()")
fi
export ZENODO_API_BASE="http://127.0.0.1:$PORT/api"
export ZENODO_TOKEN="test-token-not-a-real-credential"
export PYTHONPATH="$PKG"
# Scratch space stays inside the invocation tree. An earlier build hard-coded an
# absolute path from the machine it was written on, which fails on any other box.
W="${WORKDIR:-$PWD/.e2e-proof}"
rm -rf "$W"; mkdir -p "$W"; cd "$W"

python3 "$PKG/tests/mock_zenodo.py" "$PORT" > "$W/mock.log" 2>&1 &
MOCK=$!; trap 'kill $MOCK 2>/dev/null || true' EXIT
UP=0
for i in $(seq 40); do
  curl -sf "http://127.0.0.1:$PORT/api/deposit/depositions" >/dev/null 2>&1 && { UP=1; break; }
  sleep 0.25
done
if [ "$UP" != "1" ]; then
  echo "FAIL: the local Zenodo stand-in never came up on :$PORT" >&2
  echo "--- mock log ---" >&2; cat "$W/mock.log" >&2
  exit 2
fi
echo "  mock zenodo up on :$PORT  (scratch: $W)"

cat > meta.json <<'JSON'
{
  "title": "CHAKRA — Temporal Cycle Observatory",
  "version": "1.4.1",
  "upload_type": "software",
  "description": "Astronomical observatory kernel with a byte-parity C99 twin. © 1993–2026 Abhishek Choudhary. All rights reserved.",
  "license": "gpl-3.0",
  "access_right": "open",
  "creators": [{"name": "Choudhary, Abhishek", "affiliation": "AyeAI", "orcid": "0009-0002-0684-8320"}],
  "keywords": ["astronomy", "calendars"],
  "related_identifiers": [],
  "repository": "https://github.com/project-ilm/chakra"
}
JSON
echo "v1 payload" > art.txt

M() { python3 -m misty.cli "$@"; }

echo
echo "== 1. first deposit: publish mints a concept =="
M publish -m meta.json -f art.txt --no-package --output r1.json >/dev/null 2>&1
D1=$(python3 -c "import json;print(json.load(open('r1.json'))['doi'])")
C1=$(python3 -c "import json;print(json.load(open('r1.json'))['concept_doi'])")
ID1=$(python3 -c "import json;print(json.load(open('r1.json'))['deposition_id'])")
echo "     version DOI $D1   concept $C1   id $ID1"

echo
echo "== 2. newversion: same concept, new version, inherited files cleared =="
python3 -c "
import json;m=json.load(open('meta.json'));m['version']='1.5.0';json.dump(m,open('meta.json','w'),indent=2)"
echo "v2 payload, different bytes" > art.txt
M newversion -r "$ID1" -m meta.json -f art.txt --output r2.json 2>&1 | sed -n 's/^\[misty\] /     /p'
D2=$(python3 -c "import json;print(json.load(open('r2.json'))['doi'])")
C2=$(python3 -c "import json;print(json.load(open('r2.json'))['concept_doi'])")

echo
echo "== assertions =="
python3 - "$D1" "$D2" "$C1" "$C2" "$PORT" <<'PY'
import sys, json, urllib.request
d1, d2, c1, c2, port = sys.argv[1:6]
def get(u): return json.load(urllib.request.urlopen(u))
ok = True
def ck(name, cond, detail=""):
    global ok
    print("     %-4s %s %s" % ("OK" if cond else "FAIL", name, detail))
    ok = ok and cond
ck("concept DOI preserved across the version", c1 == c2, f"{c1} == {c2}")
ck("version DOI is new", d1 != d2, f"{d1} -> {d2}")
deps = get(f"http://127.0.0.1:{port}/api/deposit/depositions?all_versions=true&size=100")
pub = [d for d in deps if d["state"] == "done"]
ck("two published versions exist", len(pub) == 2, str(len(pub)))
ck("both sit under one concept", len({d["conceptrecid"] for d in pub}) == 1)
latest = max(pub, key=lambda d: d["id"])
ck("inherited file was cleared, exactly one file remains",
   len(latest["files"]) == 1, str([f["key"] for f in latest["files"]]))
ck("latest version string recorded", latest["metadata"].get("version") == "1.5.0",
   str(latest["metadata"].get("version")))
sys.exit(0 if ok else 1)
PY

echo
echo "== 3. the damage publish-instead-of-newversion causes, and the walk finding it =="
# same title deposited again as a fresh concept — the old, wrong way
M publish -m meta.json -f art.txt --no-package --output r3.json >/dev/null 2>&1
python3 -c "import json;print('     third deposit concept:',json.load(open('r3.json'))['concept_doi'])"

cat > rules.json <<'JSON'
{
  "affiliation_must_be": "AyeAI",
  "forbidden_strings": ["Independent Researcher", "kaivalyikagi.org"],
  "expected_orcid": "0009-0002-0684-8320",
  "copyright_contains": "© 1993–2026 Abhishek Choudhary",
  "known_facts": {}
}
JSON
set +e
M walk --rules rules.json --output walk.json 2>&1 | sed -n 's/^\[misty\] /     /p;/ERROR\|WARN/p' | head -20
RC=$?
set -e
echo "     walk exit code: $RC (1 means it found errors, which it should)"
python3 -c "
import json;r=json.load(open('walk.json'))
print('     counts:',r['counts'],'| published',r['published'])
split=[f for f in r['findings'] if 'separate concept' in f['message']]
assert split, 'FAIL: walk did not detect the split lineage'
print('     OK   split lineage detected:',split[0]['observed'])"
