# `misty walk` — verifying the Zenodo record estate

© 1993–2026 Abhishek Choudhary. All rights reserved. GPL-3.0-or-later.

The walk reports. It never edits. Correcting a published record is a separate,
deliberate act, and it should stay that way.

    misty walk --rules walk.rules.json --repos ~/work/zistgah ~/work/project-ilm

Exit 1 if any ERROR-class finding, so it drops straight into CI.

## What it checks, per record

| finding | severity | why it matters |
|---|---|---|
| no DOI on a published record | ERROR | the record is not citable |
| no concept DOI | WARN | the record can never be versioned as a lineage |
| affiliation is not the configured value | ERROR | affiliation discipline |
| forbidden string anywhere in the metadata | ERROR | catches a wrong affiliation or a dead domain wherever it hides |
| ORCID absent or not the expected one | WARN / ERROR | attribution |
| no `version` string | WARN | future versions cannot be ordered; `newversion` becomes ambiguous |
| no license | WARN | reuse terms unstated |
| empty or very short description | ERROR / WARN | a record nobody can evaluate |
| description missing the copyright line | WARN | configurable |
| related identifier pointing at the record's own DOI | WARN | a citation loop |
| published record with no files | WARN | metadata-only deposit, usually unintended |
| publication date contradicting an author-asserted fact | ERROR | see `known_facts` |

## What it checks across records

**Split lineage.** The same title published under more than one concept DOI.
This is the exact signature of `publish` being used where `newversion` was
needed. It is invisible in the Zenodo web interface unless you already suspect
it, and once published only Zenodo support can merge the concepts. The walk
exists largely for this.

## What it checks against your repositories

With `--repos`, every `10.5281/zenodo.NNNN` in the scanned trees is indexed.
Any published DOI absent from that index is flagged: **published, but not
discoverable from the work itself.** A DOI recorded nowhere is a DOI nobody
will ever cite.

## Rules file

Everything is data. Nothing about your estate is hard-coded into the tool.

```json
{
  "affiliation_must_be": "AyeAI",
  "forbidden_strings": ["Independent Researcher", "kaivalyikagi.org"],
  "forbidden_affiliations": [],
  "expected_orcid": "0009-0002-0684-8320",
  "require_version": true,
  "require_license": true,
  "min_description_chars": 40,
  "copyright_contains": "© 1993–2026 Abhishek Choudhary",
  "known_facts": {
    "PEDLER": { "publication_date": "2001-11-01" }
  }
}
```

`known_facts` holds dates **you** assert, matched on normalised title. The tool
never infers a date and never proposes one; it only tells you when the record
disagrees with what you have written down.

## Offline

    misty walk --records depositions.json --rules walk.rules.json

Reads records from a file, makes no network calls. Useful in CI, and useful for
re-checking a snapshot after you have changed the rules.

## Honest limits

- It sees only what the token can see. A record deposited under another account
  is invisible to it.
- It cannot tell a correct description from a plausible one. It checks presence,
  length and forbidden strings — not truth.
- It cannot merge split concepts. Nothing outside Zenodo support can.
