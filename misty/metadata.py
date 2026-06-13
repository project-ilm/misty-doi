"""Canonical Misty metadata: load, validate, normalize.

The Misty canonical record is the *single* artifact an upstream workflow must
produce. Everything else (Zenodo / DataCite / codemeta / CFF) is derived from
it by :mod:`misty.transform`. Upstream never needs to learn a vendor schema.

Accepted input formats: JSON (always) and YAML (if PyYAML is installed).
Validation here is intentionally dependency-free; a richer JSON Schema lives in
``schemas/misty-metadata.schema.json`` for external linting and is used
automatically when ``jsonschema`` is importable.
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, List

from .errors import MetadataError

# Zenodo upload_type vocabulary (mirrors Zenodo's deposit API).
UPLOAD_TYPES = {
    "publication", "poster", "presentation", "dataset", "image",
    "video", "software", "lesson", "physicalobject", "workflow", "other",
}

# Required when upload_type == "publication".
PUBLICATION_TYPES = {
    "annotationcollection", "book", "section", "conferencepaper",
    "datamanagementplan", "article", "patent", "preprint", "deliverable",
    "milestone", "proposal", "report", "softwaredocumentation",
    "taxonomictreatment", "technicalnote", "thesis", "workingpaper", "other",
}

ACCESS_RIGHTS = {"open", "embargoed", "restricted", "closed"}

REQUIRED = ("title", "description", "creators", "license", "upload_type")


def load(path: str) -> Dict[str, Any]:
    """Load a canonical metadata file (.json / .yaml / .yml)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read()
    except OSError as exc:
        raise MetadataError(f"cannot read metadata file {path!r}: {exc}") from exc

    if path.lower().endswith((".yaml", ".yml")):
        try:
            import yaml  # type: ignore
        except ImportError as exc:
            raise MetadataError(
                "PyYAML is required to read YAML metadata; "
                "install with `pip install misty-doi[yaml]` or use JSON"
            ) from exc
        data = yaml.safe_load(text)
    else:
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise MetadataError(f"invalid JSON in {path!r}: {exc}") from exc

    if not isinstance(data, dict):
        raise MetadataError("metadata root must be a JSON/YAML object")
    return data


def validate(m: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable validation errors ([] means valid)."""
    errs: List[str] = []

    for key in REQUIRED:
        if not m.get(key):
            errs.append(f"missing required field: {key!r}")

    ut = m.get("upload_type")
    if ut and ut not in UPLOAD_TYPES:
        errs.append(f"upload_type {ut!r} not one of {sorted(UPLOAD_TYPES)}")

    if ut == "publication":
        pt = m.get("publication_type")
        if not pt:
            errs.append("publication_type is required when upload_type='publication'")
        elif pt not in PUBLICATION_TYPES:
            errs.append(f"publication_type {pt!r} not one of {sorted(PUBLICATION_TYPES)}")

    ar = m.get("access_right", "open")
    if ar not in ACCESS_RIGHTS:
        errs.append(f"access_right {ar!r} not one of {sorted(ACCESS_RIGHTS)}")
    if ar == "embargoed" and not m.get("embargo_date"):
        errs.append("embargo_date is required when access_right='embargoed'")

    creators = m.get("creators")
    if not isinstance(creators, list) or not creators:
        errs.append("creators must be a non-empty list")
    else:
        for i, c in enumerate(creators):
            if not isinstance(c, dict) or not c.get("name"):
                errs.append(f"creators[{i}].name is required (format: 'Family, Given')")
            elif ", " not in c["name"] and " " in c["name"]:
                errs.append(
                    f"creators[{i}].name {c['name']!r} should be 'Family, Given' "
                    "(comma-separated) for correct citation indexing"
                )

    # Optional richer validation against the shipped JSON Schema.
    errs.extend(_jsonschema_errors(m))
    return errs


def _jsonschema_errors(m: Dict[str, Any]) -> List[str]:
    try:
        import jsonschema  # type: ignore
    except ImportError:
        return []
    schema_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)),
        "schemas", "misty-metadata.schema.json",
    )
    if not os.path.exists(schema_path):
        return []
    try:
        with open(schema_path, encoding="utf-8") as fh:
            schema = json.load(fh)
        validator = jsonschema.Draft202012Validator(schema)
        return [f"schema: {e.message}" for e in validator.iter_errors(m)]
    except Exception:  # schema linting is advisory, never fatal
        return []


def normalize(m: Dict[str, Any]) -> Dict[str, Any]:
    """Fill defaults and tidy a validated record (does not mutate input)."""
    n = dict(m)
    n.setdefault("access_right", "open")
    n.setdefault("version", "1.0.0")
    n.setdefault("language", "eng")
    n.setdefault("keywords", [])
    # Trim creator dicts to known keys, preserving order.
    n["creators"] = [
        {k: c[k] for k in ("name", "affiliation", "orcid", "gnd") if c.get(k)}
        for c in n.get("creators", [])
    ]
    return n


def load_validate_normalize(path: str) -> Dict[str, Any]:
    """Convenience: the full intake pipeline used by every CLI command."""
    m = load(path)
    errs = validate(m)
    if errs:
        raise MetadataError(
            "metadata validation failed:\n  - " + "\n  - ".join(errs)
        )
    return normalize(m)
