#!/usr/bin/env bash
# misty :: zenodo-publish.sh
# Muh Mitha Kijiye!(TM) — Project ILM
#
# Metadata-driven, env-keyed, non-interactive Zenodo publisher. This is the
# dependency-light path (bash + curl + python3 only): no `misty` install
# required, suitable for CI runners and air-gapped-then-online workflows.
#
# CONTRACT (matches the Python CLI):
#   Upstream produces a Zenodo metadata file and exports a token. That is all.
#
# USAGE:
#   ZENODO_TOKEN=xxxx ./zenodo-publish.sh <zenodo-metadata.json> <file> [file...]
#
# The metadata file must be the Zenodo body, i.e. {"metadata": { ... }}, exactly
# as produced by:   misty transform -m misty.json -o build/   (-> build/zenodo.json)
#
# ENVIRONMENT:
#   ZENODO_TOKEN   (required) personal access token
#   ZENODO_SANDBOX (optional) 1/true -> use sandbox.zenodo.org
#   MISTY_NO_PUBLISH (optional) 1 -> create+upload+metadata, leave as draft
#   MISTY_RESULT   (optional) path to write result JSON (default: ./result.json)
#
# EXIT CODES: 0 ok | 2 usage/metadata | 3 no token | 4 zenodo error
set -uo pipefail

die() { echo "[misty] ERROR: $*" >&2; exit "${2:-1}"; }
log() { echo "[misty] $*" >&2; }

TOKEN="${ZENODO_TOKEN:-}"
[ -n "$TOKEN" ] || die "ZENODO_TOKEN not set" 3

META="${1:-}"
shift || true
[ -n "$META" ] && [ -f "$META" ] || die "usage: $0 <zenodo-metadata.json> <file> [file...]" 2
[ "$#" -ge 1 ] || die "no artifact files given" 2

if [ "${ZENODO_SANDBOX:-}" = "1" ] || [ "${ZENODO_SANDBOX:-}" = "true" ]; then
  API="https://sandbox.zenodo.org/api"; log "target: SANDBOX"
else
  API="https://zenodo.org/api"; log "target: PRODUCTION"
fi
AUTH=(-H "Authorization: Bearer $TOKEN")
RESULT="${MISTY_RESULT:-./result.json}"

# Ensure metadata file is wrapped as {"metadata": {...}}.
python3 - "$META" <<'PY' || die "metadata file is not valid {\"metadata\": {...}} JSON" 2
import json, sys
d = json.load(open(sys.argv[1]))
assert isinstance(d, dict) and "metadata" in d, "expected top-level 'metadata' key"
PY

log "creating deposition..."
DEP=$(curl -fsS -X POST "$API/deposit/depositions" "${AUTH[@]}" \
  -H "Content-Type: application/json" -d '{}') || die "create deposition failed" 4
DEP_ID=$(printf '%s' "$DEP" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
BUCKET=$(printf '%s' "$DEP" | python3 -c "import sys,json;print(json.load(sys.stdin)['links']['bucket'])")
log "deposition $DEP_ID  bucket $BUCKET"

FILES_JSON="[]"
for f in "$@"; do
  [ -f "$f" ] || die "file not found: $f" 2
  name=$(basename "$f")
  sha=$(sha256sum "$f" | cut -d' ' -f1)
  log "uploading $name (sha256 $sha)"
  curl -fsS -X PUT "$BUCKET/$name" "${AUTH[@]}" --upload-file "$f" >/dev/null \
    || die "upload $name failed" 4
  FILES_JSON=$(python3 -c "import json,sys,os;a=json.loads(sys.argv[1]);a.append({'name':sys.argv[2],'sha256':sys.argv[3],'size':os.path.getsize(sys.argv[4])});print(json.dumps(a))" "$FILES_JSON" "$name" "$sha" "$f")
done

log "setting metadata..."
curl -fsS -X PUT "$API/deposit/depositions/$DEP_ID" "${AUTH[@]}" \
  -H "Content-Type: application/json" --data-binary "@$META" >/dev/null \
  || die "set metadata failed" 4

if [ "${MISTY_NO_PUBLISH:-}" = "1" ]; then
  log "draft created (MISTY_NO_PUBLISH=1); not publishing"
  STATE="draft"; DOI=""; URL="$API/../records/$DEP_ID"
else
  log "publishing..."
  PUB=$(curl -fsS -X POST "$API/deposit/depositions/$DEP_ID/actions/publish" "${AUTH[@]}") \
    || die "publish failed" 4
  DOI=$(printf '%s' "$PUB" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('doi',''))")
  URL=$(printf '%s' "$PUB" | python3 -c "import sys,json;d=json.load(sys.stdin);print(d.get('links',{}).get('record_html',''))")
  STATE="published"
  log "PUBLISHED doi=$DOI"
fi

python3 - "$RESULT" "$STATE" "$DOI" "$URL" "$DEP_ID" "$BUCKET" "$FILES_JSON" <<'PY'
import json, sys, datetime
path, state, doi, url, dep, bucket, files = sys.argv[1:8]
res = {
  "tool": "misty-doi/zenodo-publish.sh", "state": state,
  "doi": doi or None, "record_url": url or None,
  "deposition_id": int(dep), "bucket": bucket,
  "sandbox": False, "files": json.loads(files),
  "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
}
open(path, "w").write(json.dumps(res, indent=2))
print(json.dumps(res, indent=2))
PY
log "result -> $RESULT"
