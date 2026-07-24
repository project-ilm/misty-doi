#!/usr/bin/env python3
"""Harvest the minted estate: payloads local, deduplicated, write-ups assessed.

Three jobs, in order:

  1. Pull every published record's files into a local tree, one directory per
     record. What is only on Zenodo is not yours to work on offline.
  2. Deduplicate by SHA-256 across the whole estate. The same tarball deposited
     under four records is four copies of one artifact; the walk names them and
     hard-links the duplicates so the tree stops growing.
  3. Assess each write-up against what a reviewing professor would expect, and
     propose the cross-references between records that are missing.

It never edits a Zenodo record. Cross-references are emitted as a patch file you
apply deliberately, because a related_identifier is a public claim.

© 1993–2026 Abhishek Choudhary. All rights reserved. GPL-3.0-or-later.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from collections import defaultdict
from typing import Any, Dict, List

# What a reviewing reader looks for. Absence is a finding, not a fix: the tool
# never writes prose on the author's behalf.
RUBRIC = [
    ("abstract_length", "a substantive abstract (>= 600 characters)",
     lambda d, m: len(d) >= 600),
    ("states_problem", "says what problem it addresses",
     lambda d, m: bool(re.search(r"\b(problem|gap|limitation|challenge|question|why)\b", d, re.I))),
    ("states_method", "says how the work was done",
     lambda d, m: bool(re.search(r"\b(method|approach|architecture|implement|design|algorithm|protocol)\b", d, re.I))),
    ("states_result", "says what was produced or found",
     lambda d, m: bool(re.search(r"\b(result|we (show|present|introduce|release)|provides?|delivers?|contribut)\b", d, re.I))),
    ("reproducibility", "points at code, data or a build that can be re-run",
     lambda d, m: bool(re.search(r"(github|gitlab|savannah|zenodo|doi|repository|source)", d, re.I))),
    ("has_keywords", "carries keywords for discovery",
     lambda d, m: len(m.get("keywords") or []) >= 3),
    ("has_related", "cites at least one sibling record",
     lambda d, m: len(m.get("related_identifiers") or []) >= 1),
    ("has_version", "carries a version string",
     lambda d, m: bool((m.get("version") or "").strip())),
    ("has_license", "states its licence",
     lambda d, m: bool(m.get("license"))),
]


def plain(html: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html or "")).strip()


def sha256(path: str) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# --------------------------------------------------------------- harvesting --
def download(client, records: List[Dict[str, Any]], outroot: str) -> Dict[str, Any]:
    import requests
    got, skipped, failed = [], [], []
    for r in records:
        state = r.get("state") or ("done" if r.get("submitted") else "")
        if state != "done":
            continue
        rid = r.get("id")
        doi = r.get("doi") or (r.get("metadata", {}) or {}).get("doi") or f"record-{rid}"
        d = os.path.join(outroot, str(rid))
        os.makedirs(d, exist_ok=True)
        json.dump(r, open(os.path.join(d, "record.json"), "w", encoding="utf-8"),
                  indent=2, ensure_ascii=False)
        for f in r.get("files", []) or []:
            name = f.get("key") or f.get("filename") or f.get("id")
            link = ((f.get("links") or {}).get("download")
                    or (f.get("links") or {}).get("self"))
            dest = os.path.join(d, name)
            if os.path.exists(dest) and f.get("checksum", "").endswith(
                    hashlib.md5(open(dest, "rb").read()).hexdigest()):
                skipped.append(dest)
                continue
            if not link:
                failed.append((doi, name, "no download link in the record"))
                continue
            try:
                with client._session.get(link, stream=True, timeout=300) as resp:
                    resp.raise_for_status()
                    with open(dest, "wb") as fh:
                        for chunk in resp.iter_content(1 << 20):
                            fh.write(chunk)
                got.append(dest)
            except Exception as exc:
                failed.append((doi, name, f"{type(exc).__name__}: {exc}"))
    return {"downloaded": got, "already_present": skipped, "failed": failed}


def dedupe(outroot: str, link: bool = True) -> Dict[str, Any]:
    """Identical bytes under several records become one file plus hard links."""
    by_hash: Dict[str, List[str]] = defaultdict(list)
    for dirpath, dirnames, filenames in os.walk(outroot):
        for fn in filenames:
            if fn == "record.json":
                continue
            p = os.path.join(dirpath, fn)
            if os.path.islink(p):
                continue
            by_hash[sha256(p)].append(p)

    groups = {h: sorted(v) for h, v in by_hash.items() if len(v) > 1}
    reclaimed = 0
    for h, paths in groups.items():
        keeper = paths[0]
        for dup in paths[1:]:
            if os.stat(dup).st_ino == os.stat(keeper).st_ino:
                continue
            size = os.path.getsize(dup)
            if link:
                os.replace(dup, dup + ".tmp")
                try:
                    os.link(keeper, dup)
                    os.unlink(dup + ".tmp")
                    reclaimed += size
                except OSError:
                    os.replace(dup + ".tmp", dup)
    return {"duplicate_groups": len(groups), "bytes_reclaimed": reclaimed,
            "groups": {h[:16]: p for h, p in groups.items()}}


# ------------------------------------------------------------- the write-up --
def assess(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for r in records:
        state = r.get("state") or ("done" if r.get("submitted") else "")
        if state != "done":
            continue
        m = r.get("metadata", {}) or {}
        d = plain(m.get("description", ""))
        missing = [(k, label) for k, label, test in RUBRIC if not test(d, m)]
        out.append({
            "id": r.get("id"),
            "doi": r.get("doi") or m.get("doi"),
            "title": m.get("title"),
            "abstract_chars": len(d),
            "score": len(RUBRIC) - len(missing),
            "of": len(RUBRIC),
            "missing": [label for _, label in missing],
            "missing_keys": [k for k, _ in missing],
        })
    return sorted(out, key=lambda x: x["score"])


# ------------------------------------------------------- cross-referencing --
STOP = set("""a an the of and or for to in on with without from by is are as at
into using via that this these those it its use uses used system based new
towards toward through across over under between within""".split())


def _terms(text: str) -> set:
    return {w for w in re.findall(r"[a-z][a-z0-9\-]{3,}", (text or "").lower())
            if w not in STOP}


def propose_links(records: List[Dict[str, Any]], min_shared: int = 3) -> List[Dict[str, Any]]:
    """Suggest which records should cite which, on shared vocabulary.

    A suggestion, never an assertion: the tool proposes `references`, the
    weakest honest relation, and leaves the stronger claims (isPartOf,
    isSupplementTo, isNewVersionOf) to the author, who alone knows which is true.
    """
    pub = [r for r in records
           if (r.get("state") or ("done" if r.get("submitted") else "")) == "done"]
    prof = {}
    for r in pub:
        m = r.get("metadata", {}) or {}
        # Title and keywords only. Descriptions share too much boilerplate
        # (licence, copyright, affiliation) to discriminate between records.
        prof[r["id"]] = _terms(m.get("title", "")) | _terms(" ".join(m.get("keywords") or []))
    existing = {}
    for r in pub:
        m = r.get("metadata", {}) or {}
        existing[r["id"]] = {(ri.get("identifier") or "").rstrip("/").split("/")[-1]
                             for ri in (m.get("related_identifiers") or [])}

    props = []
    ids = [r["id"] for r in pub]
    doi_of = {r["id"]: (r.get("doi") or (r.get("metadata") or {}).get("doi")) for r in pub}
    title_of = {r["id"]: (r.get("metadata", {}) or {}).get("title", "") for r in pub}
    for i, a in enumerate(ids):
        for b in ids[i + 1:]:
            shared = prof[a] & prof[b]
            if len(shared) < min_shared:
                continue
            if doi_of[b] and doi_of[b].split("/")[-1] in existing[a]:
                continue
            props.append({
                "from": a, "from_title": title_of[a][:60], "from_doi": doi_of[a],
                "to": b, "to_title": title_of[b][:60], "to_doi": doi_of[b],
                "relation": "references",
                "shared_terms": sorted(shared)[:8],
                "strength": len(shared),
            })
    return sorted(props, key=lambda p: -p["strength"])


def patch_for(props: List[Dict[str, Any]]) -> Dict[str, Any]:
    """A file you apply deliberately, not an edit the tool performs."""
    by_rec: Dict[int, List[Dict[str, str]]] = defaultdict(list)
    for p in props:
        if p["to_doi"]:
            by_rec[p["from"]].append({
                "identifier": p["to_doi"], "relation": p["relation"],
                "resource_type": "software",
                "_because": "shares: " + ", ".join(p["shared_terms"]),
            })
    return {
        "_note": ("Proposed related_identifiers. Nothing here has been applied. "
                  "Review each: `references` is the weakest honest relation; "
                  "isPartOf, isSupplementTo and isNewVersionOf are stronger claims "
                  "only you can make."),
        "_apply_with": "misty newversion -r <id> -m <updated metadata> -f <files>",
        "records": {str(k): v for k, v in by_rec.items()},
    }
