# Changelog

All notable changes to misty-doi. Newest first.

## 1.2.0 — 2026-10-05

The update features, corrected.

- `misty newversion -c <concept>` looks up the latest published version itself. Given
  `-r`, it checks that the record is the latest, because Zenodo versions only the latest,
  and names the latest when it is not. A version DOI given as the concept is resolved to
  its concept.
- It refuses a version string the latest version already carries.
- It accepts both answers Zenodo deployments give to the newversion action: the parent
  with `links.latest_draft`, or the draft itself. It refuses a draft that is already
  published or belongs to another concept.
- An unpublished version draft is reopened, not stacked; its files are cleared before the
  upload.
- Related identifiers pointing at the record's own lineage are dropped and reported:
  version relations within one concept are Zenodo's to manage.
- `--dry-run` now looks the lineage up (read-only) and reports the version it would follow;
  `--offline` keeps the old no-network dry run.
- New `misty update -c <concept> -m <metadata>`: corrects a published version's metadata
  through Zenodo's edit action. Its DOI and files do not change, and it refuses a new
  version string, which is `newversion`'s job.
- `misty latest` reports the latest version's DOI and version, and any open drafts.
- tests/test_versions.py (16 tests) runs both answer shapes against tests/mock_zenodo.py,
  which now keeps Zenodo's rules: only the latest is versioned, one open draft per concept,
  metadata replaced on PUT, an edit keeps its DOI.
- ops/verify.sh: the repository's own gate.

## 1.1.2 — 2026-07-28

- newversion, discard, walk, harvest and guard.
- kit: a ready-to-mint kit per author, so each mints under their own token.
- masi: prereg, ethics, journal, conference and chapter workflows with cross-track gates.

