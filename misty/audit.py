"""Walk every Zenodo record the token can see and check it.

Why this exists: ``publish`` always mints a brand-new concept DOI. Before
``newversion`` existed, the only way to update a record was to publish again,
which silently scattered what should have been one lineage across several
concept DOIs. That damage is invisible from the Zenodo web UI unless you go
looking. This walk goes looking.

It also checks the things that are cheap to get wrong and expensive to discover
later: an affiliation that should never appear, a missing ``version`` (which
makes future ``newversion`` calls ambiguous), an empty description, a
self-referential related identifier.

Two principles:

  * Every finding names the record, the field and the observed value. A finding
    you cannot act on is noise.
  * The walk never edits anything. It reports. Correcting a published record is
    a separate, deliberate act.

Severity: ERROR (exit non-zero), WARN (report, exit 0), INFO (context only).
"""

from __future__ import annotations

import json
import os
import re
from collections import defaultdict
from typing import Any, Dict, List, Optional

DEFAULT_RULES: Dict[str, Any] = {
    "affiliation_must_be": "AyeAI",
    "forbidden_strings": [
        "Independent Researcher",
        "kaivalyikagi.org",
    ],
    "forbidden_affiliations": [],
    "expected_orcid": None,
    "require_version": True,
    "require_license": True,
    "require_description": True,
    "min_description_chars": 40,
    "copyright_contains": None,
    "known_facts": {},
}


def load_rules(path: Optional[str]) -> Dict[str, Any]:
    rules = dict(DEFAULT_RULES)
    if path:
        with open(path, "r", encoding="utf-8") as fh:
            rules.update(json.load(fh))
    return rules


def _norm_title(t: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", (t or "").lower()).strip()


def _finding(sev: str, rec: Dict[str, Any], field: str, msg: str,
             observed: Any = None) -> Dict[str, Any]:
    meta = rec.get("metadata", {}) or {}
    return {
        "severity": sev,
        "id": rec.get("id"),
        "doi": rec.get("doi") or meta.get("doi"),
        "concept_doi": rec.get("conceptdoi") or meta.get("conceptdoi"),
        "title": (meta.get("title") or "")[:70],
        "field": field,
        "message": msg,
        "observed": observed,
    }


def check_record(rec: Dict[str, Any], rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    meta = rec.get("metadata", {}) or {}
    state = rec.get("state") or ("done" if rec.get("submitted") else "unsubmitted")

    if state != "done":
        out.append(_finding("INFO", rec, "state",
                            "unpublished draft — not part of the public record", state))
        return out

    doi = rec.get("doi") or meta.get("doi")
    if not doi:
        out.append(_finding("ERROR", rec, "doi", "published record carries no DOI"))
    if not (rec.get("conceptdoi") or meta.get("conceptdoi")):
        out.append(_finding("WARN", rec, "conceptdoi",
                            "no concept DOI — this record cannot be versioned as a lineage"))

    # creators
    for i, c in enumerate(meta.get("creators", []) or []):
        aff = (c.get("affiliation") or "").strip()
        want = rules.get("affiliation_must_be")
        if want and aff != want:
            out.append(_finding("ERROR", rec, f"creators[{i}].affiliation",
                                f"affiliation must be {want!r}", aff or "(empty)"))
        for bad in rules.get("forbidden_affiliations", []):
            if bad.lower() in aff.lower():
                out.append(_finding("ERROR", rec, f"creators[{i}].affiliation",
                                    f"forbidden affiliation {bad!r}", aff))
        exp = rules.get("expected_orcid")
        if exp:
            got = (c.get("orcid") or "").strip()
            if not got:
                out.append(_finding("WARN", rec, f"creators[{i}].orcid",
                                    "no ORCID on this creator", "(empty)"))
            elif got.replace("https://orcid.org/", "") != exp:
                out.append(_finding("ERROR", rec, f"creators[{i}].orcid",
                                    f"ORCID is not {exp}", got))
    if not (meta.get("creators") or []):
        out.append(_finding("ERROR", rec, "creators", "no creators listed"))

    # version — without it, newversion lineages become ambiguous
    if rules.get("require_version") and not (meta.get("version") or "").strip():
        out.append(_finding("WARN", rec, "version",
                            "no version string — future versions cannot be ordered",
                            "(empty)"))

    if rules.get("require_license") and not meta.get("license"):
        out.append(_finding("WARN", rec, "license", "no license recorded"))

    desc = re.sub(r"<[^>]+>", "", meta.get("description") or "").strip()
    if rules.get("require_description"):
        if not desc:
            out.append(_finding("ERROR", rec, "description", "empty description"))
        elif len(desc) < int(rules.get("min_description_chars", 40)):
            out.append(_finding("WARN", rec, "description",
                                "description is very short", f"{len(desc)} chars"))

    cw = rules.get("copyright_contains")
    if cw and cw not in desc:
        out.append(_finding("WARN", rec, "description",
                            f"description does not carry {cw!r}"))

    blob = json.dumps(meta, ensure_ascii=False)
    for bad in rules.get("forbidden_strings", []):
        if bad.lower() in blob.lower():
            out.append(_finding("ERROR", rec, "metadata",
                                f"forbidden string {bad!r} appears in the record"))

    # related identifiers must not point at the record itself
    for ri in meta.get("related_identifiers", []) or []:
        ident = (ri.get("identifier") or "").strip()
        if doi and ident and ident.rstrip("/").endswith(doi):
            out.append(_finding("WARN", rec, "related_identifiers",
                                "record relates to its own DOI", ident))

    if not (rec.get("files") or []):
        out.append(_finding("WARN", rec, "files", "published record has no files"))

    # known facts the author has asserted — checked, never invented
    facts = rules.get("known_facts", {}) or {}
    key = _norm_title(meta.get("title", ""))
    for fk, fv in facts.items():
        if _norm_title(fk) == key and fv.get("publication_date"):
            got = meta.get("publication_date")
            if got != fv["publication_date"]:
                out.append(_finding("ERROR", rec, "publication_date",
                                    f"author-asserted date is {fv['publication_date']}", got))
    return out


def check_estate(records: List[Dict[str, Any]], rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Findings that only exist across records, not within one."""
    out: List[Dict[str, Any]] = []
    published = [r for r in records
                 if (r.get("state") or ("done" if r.get("submitted") else "")) == "done"]

    by_title: Dict[str, set] = defaultdict(set)
    sample: Dict[str, Dict[str, Any]] = {}
    for r in published:
        meta = r.get("metadata", {}) or {}
        t = _norm_title(meta.get("title", ""))
        if not t:
            continue
        concept = r.get("conceptdoi") or meta.get("conceptdoi") or ("no-concept:%s" % r.get("id"))
        by_title[t].add(concept)
        sample.setdefault(t, r)

    for t, concepts in by_title.items():
        if len(concepts) > 1:
            out.append(_finding(
                "ERROR", sample[t], "conceptdoi",
                "same title published under %d separate concept DOIs — this is the "
                "signature of `publish` used where `newversion` was needed; the "
                "lineage is split and only Zenodo support can merge it"
                % len(concepts),
                sorted(concepts)))
    return out


def scan_repo_dois(roots: List[str]) -> Dict[str, Any]:
    """Which DOIs do the local repositories actually record?

    A DOI that exists on Zenodo but is nowhere in the repository is a DOI nobody
    can find. tok-doi shipped that way once.
    """
    found: Dict[str, List[str]] = defaultdict(list)
    pat = re.compile(r"10\.5281/zenodo\.\d+")
    for root in roots:
        for dirpath, dirnames, filenames in os.walk(root):
            dirnames[:] = [d for d in dirnames if d not in (".git", "node_modules")]
            for fn in filenames:
                if not fn.lower().endswith((".json", ".md", ".cff", ".txt", ".html", ".yml", ".yaml")):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    with open(p, "r", encoding="utf-8", errors="replace") as fh:
                        text = fh.read(400_000)
                except OSError:
                    continue
                for m in pat.findall(text):
                    found[m].append(os.path.relpath(p, root))
    return found


def walk(records: List[Dict[str, Any]], rules: Dict[str, Any],
         repo_roots: Optional[List[str]] = None) -> Dict[str, Any]:
    findings: List[Dict[str, Any]] = []
    for r in records:
        findings.extend(check_record(r, rules))
    findings.extend(check_estate(records, rules))

    repo_index: Dict[str, List[str]] = {}
    if repo_roots:
        repo_index = scan_repo_dois(repo_roots)
        for r in records:
            meta = r.get("metadata", {}) or {}
            doi = r.get("doi") or meta.get("doi")
            state = r.get("state") or ("done" if r.get("submitted") else "")
            if state == "done" and doi and doi not in repo_index:
                findings.append(_finding(
                    "WARN", r, "doi",
                    "DOI is not recorded anywhere in the scanned repositories — "
                    "published but not discoverable from the work itself", doi))

    counts = {s: sum(1 for f in findings if f["severity"] == s)
              for s in ("ERROR", "WARN", "INFO")}
    published = sum(1 for r in records
                    if (r.get("state") or ("done" if r.get("submitted") else "")) == "done")
    return {
        "tool": "misty-doi walk",
        "records_seen": len(records),
        "published": published,
        "drafts": len(records) - published,
        "counts": counts,
        "findings": findings,
        "repo_dois_indexed": len(repo_index),
    }
