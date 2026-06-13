# CLI Reference

```
misty <command> [options]
misty --version
```

All commands are non-interactive. Human status → stderr; machine JSON → stdout.

---

## `misty init`

Write a metadata template to start from.

```
misty init [-o misty.json] [--force]
```

---

## `misty validate`

Validate a canonical metadata file. Exit `2` if invalid.

```
misty validate -m misty.json
```

---

## `misty transform`

Emit `zenodo.json`, `datacite.json`, `codemeta.json`, `CITATION.cff`, and the
canonical `metadata.json` into a directory. No artifacts, no network.

```
misty transform -m misty.json -o build/
```

---

## `misty package`

Build a complete offline `doi-package/` — artifacts copied in, per-file
`.sha256`, all metadata targets, `manifest.json`, and a `README.md`.

```
misty package -m misty.json -f artifact.zip [more.tar.gz …] \
              -o doi-package/ [--doi 10.5281/zenodo.X] [--output manifest.json]
```

---

## `misty publish`

The one-shot automation command. Validate → build offline package → create
Zenodo deposition → upload files → set metadata → publish → emit result.

```
misty publish -m misty.json -f artifact.zip [more …] [options]
```

| Option | Effect |
| --- | --- |
| `--sandbox` | use `sandbox.zenodo.org` (or set `ZENODO_SANDBOX=1`) |
| `--dry-run` | build the package, make **no** network calls |
| `--no-publish` | create + upload + set metadata, leave as a **draft** |
| `--no-package` | skip building the offline `doi-package/` |
| `--package-dir D` | where to write the offline package (default `doi-package`) |
| `--token T` | override `ZENODO_TOKEN` (discouraged; prefer the env var) |
| `--output P` | also write the result JSON to `P` |

Token: read from `ZENODO_TOKEN` unless `--token` is given. `ORCID` from the
environment is applied to creators lacking one.

---

## `misty ots`

OpenTimestamps proofs (requires the `ots` client: `pip install "misty-doi[ots]"`).

```
misty ots stamp   doi-package/artifact.zip     # writes artifact.zip.ots
misty ots verify  doi-package/artifact.zip      # checks the proof beside it
misty ots upgrade doi-package/artifact.zip.ots  # complete a pending proof
```

---

## Exit codes

`0` ok · `1` generic · `2` metadata · `3` config/creds · `4` zenodo · `5` ots.
See [`AUTOMATION.md`](AUTOMATION.md) for the full contract.
