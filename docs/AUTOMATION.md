# Automation & Integration Contract

Misty is built so that **any** workflow — a Makefile, a GitHub Action, a GitLab
pipeline, a research data manager, a nightly cron job — can mint a DOI without
embedding Zenodo-specific logic. This document is the stable contract that
contract that callers depend on.

---

## 1. The minimal integration

An integrating workflow has exactly three responsibilities:

1. **Produce canonical metadata** — a `misty.json` (or `.yaml`) conforming to
   [`docs/METADATA.md`](METADATA.md) / `schemas/misty-metadata.schema.json`.
2. **Export the token** — `ZENODO_TOKEN` in the environment.
3. **Call one command** — `misty publish -m misty.json -f <files…>`.

Misty owns everything else: validation, checksums, all vendor-format
generation, the deposit/upload/metadata/publish dance, retries, and the
result hand-off.

```bash
export ZENODO_TOKEN="$MY_SECRET"
misty publish -m misty.json -f build/release.zip --output result.json
DOI=$(jq -r .doi result.json)
```

---

## 2. Configuration is environment-only

No flag is *required* to carry a secret, and Misty never prompts.

| Variable | Purpose | Default |
| --- | --- | --- |
| `ZENODO_TOKEN` | Zenodo personal access token (**required** for network ops) | — |
| `ZENODO_SANDBOX` | `1`/`true` → publish to `sandbox.zenodo.org` | unset → production |
| `ORCID` | ORCID applied to creators that don't specify one | unset |

`--token` and `--sandbox` exist as overrides but are discouraged in automation
(a flag can leak into process listings and logs; an env var is the norm for
secret handling in CI).

---

## 3. Output is a machine contract

- **stdout** carries one JSON object — the *result* — and nothing else.
- **stderr** carries human `[misty] …` status lines.
- `--output PATH` additionally writes the same JSON to a file.

So both of these work cleanly:

```bash
DOI=$(misty publish -m misty.json -f a.zip | jq -r .doi)
misty publish -m misty.json -f a.zip --output result.json
```

Result object shape:

```json
{
  "tool": "misty-doi",
  "state": "published",
  "doi": "10.5281/zenodo.1234567",
  "concept_doi": "10.5281/zenodo.1234566",
  "record_url": "https://zenodo.org/records/1234567",
  "deposition_id": 1234567,
  "bucket": "https://zenodo.org/api/files/…",
  "sandbox": false,
  "files": [{"name": "a.zip", "size": 1024, "sha256": "…"}],
  "generated_at": "2026-06-13T12:00:00+00:00"
}
```

`state` is one of `published`, `draft` (with `--no-publish`), or `dry-run`.

---

## 4. Exit codes

Stable and branchable — no log scraping required.

| Code | Meaning | Typical cause |
| ---: | --- | --- |
| `0` | success | — |
| `1` | generic error | unexpected failure |
| `2` | metadata error | missing/invalid fields, file not found |
| `3` | config/credential error | `ZENODO_TOKEN` unset, `requests` missing |
| `4` | Zenodo error | API rejection or outage (after retries) |
| `5` | OpenTimestamps error | `ots` not installed / proof failed |

```bash
if ! misty publish -m misty.json -f a.zip --output result.json; then
  case $? in
    2) echo "fix your metadata" ;;
    3) echo "set ZENODO_TOKEN" ;;
    4) echo "zenodo is unhappy; retry later" ;;
  esac
fi
```

---

## 5. Safety rails for unattended runs

- `--dry-run` — validate, checksum, and build the offline package, but make
  **zero** network calls. Ideal for PR checks.
- `--sandbox` / `ZENODO_SANDBOX=1` — rehearse the full publish against Zenodo's
  sandbox, which mints test DOIs you can discard.
- `--no-publish` — create the deposition and upload files but leave it as a
  **draft** for human review before the irreversible publish step.
- Publishing a Zenodo record is permanent. Gate the real run behind a tag, a
  manual approval, or a sandbox success.

---

## 6. Recipes

### Make

```makefile
release.zip: $(SOURCES)
	zip -qr $@ $^

publish: release.zip misty.json
	misty publish -m misty.json -f release.zip --output result.json

publish-test: release.zip misty.json
	misty publish -m misty.json -f release.zip --sandbox --output result.json
```

### GitHub Actions (publish on tag)

```yaml
name: mint-doi
on:
  push:
    tags: ["v*"]
jobs:
  doi:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install misty-doi
      - run: zip -qr release.zip src/
      - run: misty publish -m misty.json -f release.zip --output result.json
        env:
          ZENODO_TOKEN: ${{ secrets.ZENODO_TOKEN }}
      - uses: actions/upload-artifact@v4
        with: { name: doi-result, path: result.json }
```

### Pure-shell (no Python package)

```bash
misty transform -m misty.json -o build/    # or hand-write build/zenodo.json
ZENODO_TOKEN=… ./scripts/zenodo-publish.sh build/zenodo.json release.zip
```

### Chaining into a timestamp + commit

```bash
misty publish -m misty.json -f release.zip --output result.json
misty ots stamp doi-package/release.zip
git add doi-package result.json && git commit -m "DOI $(jq -r .doi result.json)"
```

---

## 7. Versioning the contract

The result JSON keys, env-var names, and exit codes are treated as a public
API and will only change across a **major** version of `misty-doi`. New keys
may be added in minor versions; existing keys will not be repurposed.
