# `misty newversion` — adding a version instead of a new record

© 1993–2026 Abhishek Choudhary. All rights reserved. GPL-3.0-or-later.

`misty publish` always mints a **brand-new concept DOI**. That is correct for a
first deposit and wrong for every deposit after it. Using `publish` to update an
existing artifact silently splits one lineage across several unrelated concept
DOIs, and the split cannot be undone without Zenodo support.

`newversion` is the other half:

    misty newversion -r 21436550 -m misty.json -f build/fakir-0.7.tar.gz --new-version 0.7.0

- `-r` is the deposition id of the **latest published version**, not the concept.
- The concept DOI is preserved. A citation of the concept keeps resolving to the
  newest version.
- A fresh version DOI is minted beneath it.

## The part that is easy to get wrong

A new-version draft arrives **carrying the previous version's files**. Upload
replacements without clearing and the published record contains both, with
nothing to tell a downloader which is current.

`--replace-files` (the default) clears the inherited files first.
`--keep-files` is available when you genuinely mean to accumulate.

## Safety

    misty newversion ... --dry-run      # checksums and plan, no network
    misty newversion ... --no-publish   # leaves a draft you can inspect
    misty discard <draft-id>            # the only undo Zenodo offers

`--no-publish` prints the discard command for the draft it just created.

## How this was verified

Live Zenodo was **not** contacted. Minting is irreversible, and a test that
mints cannot be run twice. `tests/mock_zenodo.py` implements the deposit API
subset with Zenodo's concept/version semantics, and `e2e_misty.sh` proves
against it that: publish mints a concept; newversion preserves that concept
while minting a new version DOI; inherited files are cleared; the version string
lands on the record; and the walk detects a deliberately split lineage.

Point the client at a stand-in with `ZENODO_API_BASE`. Against the real service,
sandbox first: `ZENODO_SANDBOX=1`.
