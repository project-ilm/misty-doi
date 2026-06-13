# Canonical Metadata Reference

The canonical Misty record (`misty.json` / `misty.yaml`) is the only file you
author. Misty derives `zenodo.json`, `datacite.json`, `codemeta.json`, and
`CITATION.cff` from it. Machine schema: `schemas/misty-metadata.schema.json`.

## Fields

| Field | Required | Type | Notes |
| --- | :---: | --- | --- |
| `title` | ✓ | string | Full title of the work |
| `description` | ✓ | string | Abstract. HTML allowed (Zenodo renders it); stripped for CFF/DataCite |
| `creators` | ✓ | list | See *Creators* below; ≥ 1 |
| `license` | ✓ | string | Zenodo license id, e.g. `gpl-3.0`, `mit`, `cc-by-4.0` |
| `upload_type` | ✓ | enum | `software`, `dataset`, `publication`, `poster`, `presentation`, `image`, `video`, `lesson`, `workflow`, `physicalobject`, `other` |
| `publication_type` | cond. | string | Required when `upload_type = publication` (e.g. `article`, `preprint`, `report`) |
| `version` | | string | Default `1.0.0` |
| `access_right` | | enum | `open` (default), `embargoed`, `restricted`, `closed` |
| `embargo_date` | cond. | date | Required when `access_right = embargoed` |
| `language` | | string | ISO 639-3, default `eng` |
| `keywords` | | list[string] | Subject tags |
| `communities` | | list | `[{"identifier": "…"}]` |
| `grants` | | list | Funding references |
| `related_identifiers` | | list | `{"relation": …, "identifier": …, "resource_type": …}` |
| `references` | | list[string] | Free-text references |
| `dates` | | list | `{"date": "YYYY-MM-DD", "type": "Created", "description": …}` |
| `notes` | | string | Additional notes |
| `doi` | | string | Pre-reserved DOI, if any |
| `repository` | | string | Source repo URL → codemeta `codeRepository`, CFF `repository-code` |
| `programming_language` | | list[string] | → codemeta `programmingLanguage` |

### Creators

```json
"creators": [
  {"name": "Choudhary, Abhishek", "affiliation": "AyeAI", "orcid": "0000-0001-2345-6789"}
]
```

- `name` **must** be `Family, Given` (comma-separated) for correct citation
  indexing. Misty warns otherwise.
- `affiliation`, `orcid`, `gnd` are optional. A bare ORCID (no URL) is expected;
  Misty prefixes `https://orcid.org/` where the target format needs a URL.
- The bundled `examples/romenagri/misty.json` uses the placeholder ORCID
  `0000-0000-0000-0000` to demonstrate the field shape — replace it with your
  real ORCID (or remove the key) before minting a real DOI.

## How fields map to each target

| Canonical | Zenodo | DataCite | codemeta | CFF |
| --- | --- | --- | --- | --- |
| `title` | `title` | `titles[].title` | `name` | `title` |
| `description` | `description` (HTML) | `descriptions[]` (stripped) | `description` | `abstract` (stripped) |
| `creators[].name` | `creators[].name` | `creators[]` (split) | `author[]` (split) | `authors[]` (split) |
| `license` | `license` (Zenodo id) | `rightsList[]` (SPDX) | `license` (SPDX URL) | `license` (SPDX) |
| `upload_type` | `upload_type` | `types.resourceTypeGeneral` | `@type` SoftwareSourceCode | — |
| `version` | `version` | `version` | `version` | `version` |
| `doi` | (assigned on publish) | `identifiers[]` | `identifier` | `doi` |
| `repository` | (via related_identifiers) | `relatedIdentifiers[]` | `codeRepository` | `repository-code` |

License ids are translated to SPDX via a table in `misty/transform.py`
(`gpl-3.0` → `GPL-3.0-or-later`, etc.). Add entries there for licenses not yet
mapped.

## Minimal valid record

```json
{
  "title": "My Tool",
  "description": "What it does.",
  "license": "mit",
  "upload_type": "software",
  "creators": [{"name": "Doe, Jane"}]
}
```

## Validate before you publish

```bash
misty validate -m misty.json
```

Install `jsonschema` (`pip install "misty-doi[schema]"`) for full structural
validation against the shipped JSON Schema; without it Misty still runs its
built-in required-field and conditional checks.
