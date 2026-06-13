"""Offline tests for metadata + transforms (no network)."""
import json

import pytest

from misty import metadata, transform, package

GOOD = {
    "title": "Test Artifact",
    "version": "0.1.0",
    "upload_type": "software",
    "description": "<p>Hello</p> world",
    "license": "gpl-3.0",
    "access_right": "open",
    "creators": [{"name": "Choudhary, Abhishek", "affiliation": "AyeAI",
                  "orcid": "0000-0001-2345-6789"}],
    "keywords": ["a", "b"],
}


def test_valid_metadata_passes():
    assert metadata.validate(GOOD) == []


def test_missing_required_fails():
    bad = dict(GOOD)
    del bad["title"]
    errs = metadata.validate(bad)
    assert any("title" in e for e in errs)


def test_publication_requires_type():
    bad = dict(GOOD, upload_type="publication")
    errs = metadata.validate(bad)
    assert any("publication_type" in e for e in errs)


def test_embargo_requires_date():
    bad = dict(GOOD, access_right="embargoed")
    assert any("embargo_date" in e for e in metadata.validate(bad))


def test_zenodo_shape():
    z = transform.to_zenodo(metadata.normalize(GOOD))
    assert z["title"] == GOOD["title"]
    assert z["creators"][0]["orcid"] == "0000-0001-2345-6789"
    assert "files" not in z  # canonical-only keys are stripped


def test_spdx_mapping():
    assert transform.spdx("gpl-3.0") == "GPL-3.0-or-later"
    assert transform.spdx("mit") == "MIT"


def test_cff_is_parseable_yaml():
    yaml = pytest.importorskip("yaml")
    doc = yaml.safe_load(transform.to_cff(metadata.normalize(GOOD)))
    assert doc["cff-version"] == "1.2.0"
    assert doc["authors"][0]["family-names"] == "Choudhary"
    assert doc["abstract"] == "Hello world"  # HTML stripped


def test_codemeta_author_split():
    cm = transform.to_codemeta(metadata.normalize(GOOD))
    assert cm["author"][0]["familyName"] == "Choudhary"
    assert cm["author"][0]["givenName"] == "Abhishek"


def test_datacite_basic():
    dc = transform.to_datacite(metadata.normalize(GOOD))
    assert dc["types"]["resourceTypeGeneral"] == "Software"
    assert dc["titles"][0]["title"] == GOOD["title"]


def test_package_build(tmp_path):
    art = tmp_path / "a.zip"
    art.write_bytes(b"payload")
    manifest = package.build_package(metadata.normalize(GOOD), [str(art)],
                                     str(tmp_path / "pkg"))
    pkg = tmp_path / "pkg"
    for f in ("metadata.json", "zenodo.json", "datacite.json",
              "codemeta.json", "CITATION.cff", "manifest.json", "README.md",
              "a.zip", "a.zip.sha256"):
        assert (pkg / f).exists(), f
    assert manifest["artifacts"][0]["name"] == "a.zip"
    assert len(manifest["artifacts"][0]["sha256"]) == 64
