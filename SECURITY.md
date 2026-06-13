# Security Policy

## The token
- Misty reads `ZENODO_TOKEN` **only** from the environment (CLI) or holds it
  **only** in the browser tab (web UI). It is never written to disk, never
  logged, and never sent anywhere except the Zenodo API over HTTPS.
- Prefer the env var over `--token`: command-line flags can appear in process
  listings and shell history.
- Scope your Zenodo token to `deposit:write` / `deposit:actions` only.

## No telemetry
Misty makes no network calls other than to Zenodo (publishing) and, if you run
`misty ots`, to OpenTimestamps calendar servers via the `ots` client. There is
no analytics, no phone-home, no backend.

## Browser mode
The web UI runs entirely client-side. Your token stays in the tab's memory.
Project ILM operates no server and receives nothing. Use at your own risk and
prefer the CLI for unattended or high-value publishing.

## Reporting a vulnerability
Email the maintainers (see repository profile) with details and a reproduction.
Please do not open a public issue for sensitive reports.
