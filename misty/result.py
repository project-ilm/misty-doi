"""The machine-readable result a publish run hands back to its caller.

A single ``result.json`` is the automation hand-off: a downstream step reads
``doi`` / ``record_url`` and proceeds. The same structure is printed to stdout
so a pipeline can do ``DOI=$(misty publish ... | jq -r .doi)``.
"""

from __future__ import annotations

import datetime
from typing import Any, Dict, List, Optional


def build(
    *,
    deposition_id: Optional[int],
    bucket: Optional[str],
    sandbox: bool,
    files: List[Dict[str, Any]],
    doi: Optional[str] = None,
    concept_doi: Optional[str] = None,
    record_url: Optional[str] = None,
    state: str = "draft",
) -> Dict[str, Any]:
    return {
        "tool": "misty-doi",
        "state": state,                 # "draft" | "published"
        "doi": doi,
        "concept_doi": concept_doi,
        "record_url": record_url,
        "deposition_id": deposition_id,
        "bucket": bucket,
        "sandbox": sandbox,
        "files": files,
        "generated_at": datetime.datetime.now(datetime.timezone.utc)
        .isoformat(timespec="seconds"),
    }


def from_zenodo_record(record: Dict[str, Any], *, sandbox: bool,
                       files: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Extract the result fields from a published Zenodo deposition payload."""
    doi = record.get("doi")
    meta = record.get("metadata", {}) or {}
    concept = record.get("conceptdoi") or meta.get("conceptdoi")
    links = record.get("links", {}) or {}
    record_url = links.get("record_html") or links.get("html")
    return build(
        deposition_id=record.get("id"),
        bucket=links.get("bucket"),
        sandbox=sandbox,
        files=files,
        doi=doi,
        concept_doi=concept,
        record_url=record_url,
        state="published",
    )
