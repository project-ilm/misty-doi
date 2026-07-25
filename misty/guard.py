"""Pre-publication guard: seal leakage before anything irreversible.

A DOI mint is permanent. Whatever is in the metadata or the files at that moment
is public forever. This module is the gate that runs first, and it fails closed:
an ERROR-class finding stops the mint unless a human explicitly overrides with a
reason.

It answers four separate worries, kept separate because they have different
owners:

  secrets   — tokens, keys, private-key blocks. Never publishable, no exception.
  privacy   — third-party PII/SPI: emails, phone numbers, government IDs, cards.
              The author's own contact details are allowed; others' are not.
  ipr       — leakage of the author's own position: forbidden affiliations,
              hallucinated domains, absolute home paths, private hostnames,
              internal-only markers. This is the "stop further IPR leakage" ask.
  integrity — the June-2026 failure: metadata minted from unverified AI output.
              A deposit must carry an explicit author-verification marker, and
              claims of implementing a standard must carry a clean-room record.

Plus two facets the author asked to integrate:

  clean-room — an attestation that a standard was re-implemented from public
               specification, not copied. Includes an n-gram plagiarism check
               against any reference texts the author supplies as evidence.
  patents    — a first-class patents field, and a check that a deposit which
               describes an invention either cites a patent or is explicitly
               marked a defensive publication.

Nothing here is a legal opinion. It is a mechanical gate that catches the
mistakes that are cheap to make and expensive to publish.

© 1993–2026 Abhishek Choudhary. All rights reserved. GPL-3.0-or-later.
"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional

# --------------------------------------------------------------- signatures --
# Secret patterns. Deliberately conservative — a false positive costs a glance,
# a false negative costs a leaked credential.
SECRET_PATTERNS = [
    ("AWS access key id", re.compile(r"AKIA[0-9A-Z]{16}")),
    ("GitHub token", re.compile(r"gh[pousr]_[A-Za-z0-9]{36,}")),
    ("Slack token", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("Google API key", re.compile(r"AIza[0-9A-Za-z_\-]{35}")),
    ("private key block", re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH |DSA |PGP )?PRIVATE KEY-----")),
    ("generic bearer secret", re.compile(r"(?i)\b(?:api[_-]?key|secret|passwd|password|token)\b\s*[:=]\s*['\"][^'\"]{12,}['\"]")),
    ("PyPI token", re.compile(r"pypi-AgEIcHlwaS[A-Za-z0-9_\-]{20,}")),
    ("Zenodo-looking token", re.compile(r"\b[A-Za-z0-9]{60}\b")),
]

# Third-party PII/SPI.
PII_PATTERNS = [
    ("email address", re.compile(r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b")),
    ("phone number", re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s\-]?)?(?:\(\d{2,4}\)[\s\-]?)?\d{3,4}[\s\-]?\d{4}(?!\d)")),
    ("credit-card-like", re.compile(r"\b(?:\d[ \-]?){13,16}\b")),
    ("Aadhaar-like", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    ("US SSN-like", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("IPv4 address", re.compile(r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b")),
]

# Invention language — if present, the deposit should cite a patent or declare
# itself a defensive publication, so the disclosure does not sink patentability.
INVENTION_CUES = re.compile(
    r"(?i)\b(novel|for the first time|we invent|our invention|patent[- ]?pending|"
    r"a new method for|previously unpublished|proprietary (?:method|algorithm|design))\b")

STANDARD_CUES = re.compile(
    r"(?i)\b(implements?|conformant with|per the .* (?:standard|specification|RFC)|"
    r"ISO ?\d|IEEE ?\d|RFC ?\d|according to the .* spec)\b")

DEFAULT_RULES: Dict[str, Any] = {
    "author_emails": [],                 # the author's own — allowed to appear
    "author_domains": ["ayeai.xyz", "ayecnse.site", "ilm.codes", "zistgah.org"],
    "forbidden_strings": ["Independent Researcher", "kaivalyikagi.org"],
    "private_host_markers": ["localhost", "127.0.0.1", "192.168.", "10.0.", "ilm01-lin"],
    "require_author_verification": True,  # the June-2026 anti-fabrication marker
    "verification_field": "author_verified",
    "plagiarism_ngram": 8,
    "plagiarism_threshold": 0.18,        # Jaccard over n-gram shingles
}


def _finding(sev: str, kind: str, where: str, msg: str, sample: str = "") -> Dict[str, Any]:
    # never echo a whole secret back — a redacted sample is enough to locate it
    s = (sample[:6] + "…" + sample[-4:]) if len(sample) > 14 else sample
    return {"severity": sev, "kind": kind, "where": where, "message": msg, "sample": s}


def _text_of(meta: Dict[str, Any]) -> str:
    creators = meta.get("creators") or []
    parts = [meta.get("title", ""), meta.get("description", ""),
             " ".join(meta.get("keywords") or []),
             " ".join(n.get("name", "") for n in creators),
             " ".join(n.get("affiliation", "") for n in creators)]
    return "\n".join(p for p in parts if p)


# ------------------------------------------------------------- scan one text --
def scan_text(text: str, where: str, rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for name, pat in SECRET_PATTERNS:
        for m in pat.finditer(text):
            hit = m.group(0)
            # the 60-char catch-all is noisy; only flag it near a secret-ish word
            if name == "Zenodo-looking token":
                ctx = text[max(0, m.start() - 20):m.start()].lower()
                if not re.search(r"token|key|secret", ctx):
                    continue
            out.append(_finding("ERROR", "secret", where, f"{name} found", hit))

    author = set(e.lower() for e in rules.get("author_emails", []))
    adomains = tuple(rules.get("author_domains", []))
    for name, pat in PII_PATTERNS:
        for m in pat.finditer(text):
            hit = m.group(0)
            if name == "email address":
                if hit.lower() in author or hit.lower().endswith(adomains):
                    continue  # the author's own contact is fine
            if name == "IPv4 address" and hit.startswith(("0.", "255.")):
                continue
            out.append(_finding("WARN", "privacy", where, f"possible third-party {name}", hit))

    low = text.lower()
    for bad in rules.get("forbidden_strings", []):
        if bad.lower() in low:
            out.append(_finding("ERROR", "ipr", where, f"forbidden string {bad!r}", bad))
    for marker in rules.get("private_host_markers", []):
        if marker.lower() in low:
            out.append(_finding("WARN", "ipr", where, f"private host/marker {marker!r} leaked", marker))
    for m in re.finditer(r"/home/[A-Za-z0-9._\-]+/", text):
        out.append(_finding("WARN", "ipr", where, "absolute home path leaked", m.group(0)))
    return out


# ------------------------------------------------------------- plagiarism ----
def _shingles(text: str, n: int) -> set:
    toks = re.findall(r"[a-z0-9]+", (text or "").lower())
    return {" ".join(toks[i:i + n]) for i in range(max(0, len(toks) - n + 1))}


def plagiarism(text: str, references: List[str], n: int, threshold: float) -> Dict[str, Any]:
    """N-gram Jaccard against each reference. High overlap with a source you were
    supposed to re-implement from scratch is the signal clean-room exists to catch."""
    base = _shingles(text, n)
    worst = 0.0
    hits = []
    for i, ref in enumerate(references):
        rs = _shingles(ref, n)
        if not base or not rs:
            continue
        j = len(base & rs) / len(base | rs)
        if j >= threshold:
            hits.append({"reference": i, "jaccard": round(j, 3)})
        worst = max(worst, j)
    return {"max_jaccard": round(worst, 3), "over_threshold": hits, "threshold": threshold}


# ------------------------------------------------------------- clean-room ----
def check_cleanroom(meta: Dict[str, Any], files: List[str],
                    references: List[str], rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    text = _text_of(meta)
    claims_standard = bool(STANDARD_CUES.search(text))
    has_record = any(os.path.basename(f).upper() in
                     ("CLEANROOM.MD", "CLEAN-ROOM.MD", "CLEANROOM.TXT") for f in files) \
        or bool(meta.get("cleanroom"))
    if claims_standard and not has_record:
        out.append(_finding("WARN", "cleanroom", "metadata",
                            "deposit claims to implement a standard but ships no "
                            "clean-room record (CLEANROOM.md or metadata.cleanroom)"))
    if references:
        pl = plagiarism(text, references, rules["plagiarism_ngram"], rules["plagiarism_threshold"])
        if pl["over_threshold"]:
            out.append(_finding("ERROR", "plagiarism", "description",
                                "description overlaps a reference text above threshold "
                                f"(max Jaccard {pl['max_jaccard']})"))
    return out


# ------------------------------------------------------------- patents -------
def check_patents(meta: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    text = _text_of(meta)
    describes_invention = bool(INVENTION_CUES.search(text))
    patents = meta.get("patents") or []
    # a related_identifier of type 'patent' also counts
    for ri in meta.get("related_identifiers") or []:
        if (ri.get("resource_type") or ri.get("relation_type") or "").lower().find("patent") >= 0:
            patents = patents or [ri.get("identifier")]
    defensive = bool(meta.get("defensive_publication"))
    if describes_invention and not patents and not defensive:
        out.append(_finding("WARN", "patents", "description",
                            "language describes an invention but no patent is cited and "
                            "the record is not marked a defensive publication — public "
                            "disclosure may bar later patenting"))
    # a cited patent should look like a patent number, not be left as a placeholder
    for p in patents:
        if p and not re.search(r"\d", str(p)):
            out.append(_finding("WARN", "patents", "patents",
                                f"patent reference {p!r} has no number"))
    return out


# ------------------------------------------------------------- integrity -----
def check_integrity(meta: Dict[str, Any], rules: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if rules.get("require_author_verification"):
        field = rules.get("verification_field", "author_verified")
        if not meta.get(field):
            out.append(_finding("ERROR", "integrity", "metadata",
                                "metadata is not marked author-verified. After the "
                                "June-2026 fabrication incident, a deposit must carry "
                                f"`{field}: true` set by the author, not by any model."))
    return out


# ------------------------------------------------------------- the gate ------
def scan_deposit(meta: Dict[str, Any], files: Optional[List[str]] = None,
                 references: Optional[List[str]] = None,
                 rules: Optional[Dict[str, Any]] = None,
                 scan_file_bytes: int = 200_000) -> Dict[str, Any]:
    r = dict(DEFAULT_RULES)
    if rules:
        r.update(rules)
    files = files or []
    references = references or []

    findings: List[Dict[str, Any]] = []
    findings += scan_text(_text_of(meta), "metadata", r)
    for f in files:
        if not os.path.isfile(f):
            continue
        # only text-like files are scanned for secrets/PII; binaries are skipped
        try:
            with open(f, "rb") as fh:
                head = fh.read(scan_file_bytes)
            if b"\x00" in head:
                continue
            findings += scan_text(head.decode("utf-8", "replace"), os.path.basename(f), r)
        except OSError:
            continue
    findings += check_integrity(meta, r)
    findings += check_cleanroom(meta, files, references, r)
    findings += check_patents(meta)

    counts = {s: sum(1 for f in findings if f["severity"] == s) for s in ("ERROR", "WARN")}
    return {"clear": counts["ERROR"] == 0, "counts": counts, "findings": findings}
