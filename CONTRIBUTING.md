# Contributing to Misty DOI

Thanks for helping. A few ground rules keep the project predictable.

## Principles
- **Automation-first.** Any feature must work non-interactively, with secrets
  only from the environment. If it needs a prompt, it is not done.
- **No backend.** Misty never ships a server. The browser and CLI are the only
  surfaces.
- **Stable contract.** The result-JSON keys, env-var names, and exit codes are
  a public API (see `docs/AUTOMATION.md`). Breaking them needs a major bump.

## Dev setup
```bash
pip install -e ".[dev]"
pytest -q
```

## Pull requests
- Add/adjust tests for any behaviour change (`tests/`).
- Run `misty publish ... --sandbox` against Zenodo sandbox before claiming a
  publishing change works.
- Keep new dependencies out of the core; put optional ones behind extras.

## Reporting issues
Open an issue with the metadata that triggered it (redact tokens) and the exit
code. For security reports see `SECURITY.md`.
