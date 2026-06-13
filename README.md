# Misty DOI

### *Muh Mitha Kijiye!*&trade;

Browser-first, CLI-first, **automation-first** DOI minting and research/artifact
publication packaging. No backend, no subscription, no vendor lock-in.

> **Project ILM** · Copyright &copy; 1993–2026 Abhishek Choudhary · GPL-3.0-or-later

Misty turns a *single* canonical metadata file into a complete, reproducible
publication package — Zenodo deposit, DataCite record, `codemeta.json`,
`CITATION.cff`, SHA-256 checksums, OpenTimestamps proofs — and mints a DOI on
Zenodo. The same logic runs in your terminal, your CI pipeline, or fully in the
browser with no server.

---

## The one idea

**Separate metadata from mechanism.** Any workflow that wants a DOI only has to:

1. produce a canonical metadata file (`misty.json`),
2. export `ZENODO_TOKEN`,
3. call one command.

Everything vendor-specific (Zenodo's API shape, DataCite's schema, CFF's YAML)
is *derived* by Misty. Upstream never learns a vendor format. See
[`docs/AUTOMATION.md`](docs/AUTOMATION.md) for the full integration contract.

```bash
export ZENODO_TOKEN=…           # the only secret, only from the environment
misty publish -m misty.json -f artifact.zip --output result.json
DOI=$(jq -r .doi result.json)   # done
```

---

## Install

```bash
pip install misty-doi              # core (requests only)
pip install "misty-doi[all]"       # + YAML, JSON-Schema, OpenTimestamps
```

No-install path (CI / air-gapped): `scripts/zenodo-publish.sh` needs only
`bash`, `curl`, and `python3`.

---

## CLI in 60 seconds

```bash
misty init                                   # write a metadata template
misty validate -m misty.json                 # check it
misty transform -m misty.json -o build/      # -> zenodo/datacite/codemeta/CFF
misty package  -m misty.json -f a.zip -o doi-package/   # offline package + checksums
misty publish  -m misty.json -f a.zip        # deposit + upload + publish -> DOI
misty publish  -m misty.json -f a.zip --sandbox        # rehearse on sandbox.zenodo.org
misty publish  -m misty.json -f a.zip --dry-run        # package only, no network
misty ots stamp doi-package/a.zip            # OpenTimestamps proof
```

Full reference: [`docs/CLI.md`](docs/CLI.md).

---

## What gets produced

```
doi-package/
├── <artifact>            artifact file(s), copied in
├── <artifact>.sha256     checksum per file
├── metadata.json         canonical Misty record
├── zenodo.json           Zenodo deposit body  {"metadata": {…}}
├── datacite.json         DataCite 4.x
├── codemeta.json         schema.org SoftwareSourceCode
├── CITATION.cff          CFF 1.2.0 (valid YAML)
├── manifest.json         release + reproducibility manifest
└── README.md             human-readable summary
```

The package contains **no secrets** and is safe to commit, attach to a GitHub
release, or hand to an air-gapped reviewer.

---

## Browser mode

Open `web/index.html` (or the GitHub Pages deployment). Build metadata in a
form, download every target file, generate copy-paste AI prompts for
metadata drafting, and — optionally — publish directly to Zenodo with a token
that **never leaves your browser**. Project ILM receives nothing.

---

## Security model

- The token is read **only** from the environment (CLI) or held **only** in the
  browser tab (web). Misty never writes it to disk and never transmits it
  anywhere except Zenodo.
- No telemetry. No backend. No accounts.
- Offline packages are deterministic and checksummed for independent
  verification.

See [`SECURITY.md`](SECURITY.md).

---

## Documentation

| Doc | Contents |
| --- | --- |
| [`docs/AUTOMATION.md`](docs/AUTOMATION.md) | Integration contract, env vars, exit codes, CI recipes |
| [`docs/METADATA.md`](docs/METADATA.md) | Canonical schema field-by-field, mapping to every target |
| [`docs/CLI.md`](docs/CLI.md) | Every command, flag, and example |

---

## License

GPL-3.0-or-later. The tool is free software; the artifacts you publish carry
whatever license you declare in your metadata.
