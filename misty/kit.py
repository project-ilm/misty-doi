"""
misty.kit — build a ready-to-mint kit for an author who is not you.

© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI.
SPDX-License-Identifier: GPL-3.0-or-later

Two artifacts, two rules. Work you authored, you mint. Work someone else
authored, you attribute — and where that author has no DOI and no citable
identity, the useful thing is not to withhold a mint but to remove every step
between them and their own, except the one only they can take: running it
under their own token.

A kit is that reduction. It carries a descriptor drafted from whatever is
known, the artifact list with digests and any proofs already obtained, and a
single command. `author_verified` is false on arrival and `misty publish`
refuses to mint until the author sets it, because only the author can certify
metadata about their own work.

This is the MASI stance made operational: the machine drafts the metadata, the
human keeps scholarly responsibility.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from typing import Any, Dict, Iterable, List, Optional

from .errors import MistyError

KIT_VERSION = "1.0"


def slugify(name: str, maxlen: int = 60) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", name.lower())
    return re.sub(r"-+", "-", s).strip("-")[:maxlen] or "author"


def _mint_sh(strict: bool) -> str:
    guard = (
        '''grep -q '"author_verified"[[:space:]]*:[[:space:]]*false' metadata.json && {
  echo "metadata.json was drafted from a public source, not by you."
  echo "Check every field, add your ORCID and affiliation, then set"
  echo "author_verified to true. misty will not mint until you have."
  exit 1; }
'''
        if strict
        else ""
    )
    return f"""#!/usr/bin/env sh
# Mint YOUR work under YOUR account. Nobody else can do this for you and
# nobody else holds your token.
set -eu

[ -n "${{ZENODO_TOKEN:-}}" ] || {{
  echo "Set your token first:  export ZENODO_TOKEN=$(cat ~/zenodo_token)"
  exit 1; }}
command -v misty >/dev/null || {{ echo "pipx install misty-doi"; exit 1; }}

{guard}
misty validate -m metadata.json
misty publish -m metadata.json $(sed -n 's/.*"path": "\\([^"]*\\)".*/-f \\1/p' artifacts.json | tr '\\n' ' ')
"""


def build_kit(
    outdir: str,
    author: str,
    metadata_draft: Dict[str, Any],
    artifacts: Iterable[Dict[str, Any]],
    *,
    proofs_from: Optional[str] = None,
    readme_extra: str = "",
    strict_verify: bool = True,
) -> Dict[str, Any]:
    """Write one self-contained kit. Returns its manifest entry."""
    d = os.path.join(outdir, slugify(author))
    if os.path.isdir(d):
        shutil.rmtree(d)          # a generated directory is rebuilt, never accumulated
    os.makedirs(d)

    arts = list(artifacts)
    if not arts:
        raise MistyError(f"kit for {author!r} has no artifacts")

    m = dict(metadata_draft)
    m.setdefault("version", "1.0.0")
    m.setdefault("access_right", "open")
    m["author_verified"] = not strict_verify
    m.setdefault(
        "notes",
        "Drafted with machine assistance from a public source. The named author is "
        "responsible for scholarly accuracy and must review before minting. ORCID and "
        "affiliation are deliberately blank — only the author can supply them.",
    )

    copied = 0
    for a in arts:
        src = a.get("proof")
        if src and proofs_from:
            p = src if os.path.isabs(src) else os.path.join(proofs_from, os.path.basename(src))
            if os.path.exists(p):
                os.makedirs(os.path.join(d, "proofs"), exist_ok=True)
                shutil.copy(p, os.path.join(d, "proofs", os.path.basename(p)))
                copied += 1

    with open(os.path.join(d, "metadata.json"), "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=2, ensure_ascii=False)
    with open(os.path.join(d, "artifacts.json"), "w", encoding="utf-8") as fh:
        json.dump(arts, fh, indent=2, ensure_ascii=False)

    mint = os.path.join(d, "mint.sh")
    with open(mint, "w", encoding="utf-8") as fh:
        fh.write(_mint_sh(strict_verify))
    os.chmod(mint, 0o755)

    with open(os.path.join(d, "README.md"), "w", encoding="utf-8") as fh:
        fh.write(_readme(author, len(arts), copied, strict_verify, readme_extra))

    return {
        "author": author,
        "slug": slugify(author),
        "artifacts": len(arts),
        "proofs": copied,
        "path": d,
        "kit_version": KIT_VERSION,
    }


def _readme(author: str, n: int, proofs: int, strict: bool, extra: str) -> str:
    proof_line = (
        f"\n{proofs} of them already carry an OpenTimestamps proof, in `proofs/`. "
        "That proof establishes the text existed on the date it was stamped, "
        "independently of any registry.\n"
        if proofs
        else ""
    )
    step1 = (
        "1. **Read `metadata.json`.** It was drafted from a public source, not by you. "
        "Correct anything wrong, add your ORCID (free at orcid.org) and your affiliation, "
        "then set `author_verified` to `true`.\n"
        if strict
        else "1. **Read `metadata.json`** and correct anything wrong.\n"
    )
    return f"""# Your work — ready to mint

{n} items published by **{author}** are listed in `artifacts.json`, each with its
address and a digest of the content as it was read.
{proof_line}
Minting gives your work a **DOI**: a permanent, citable identifier that outlives the
platform it was published on, and that carries your name.

## Three steps

{step1}2. **Get a Zenodo token** — zenodo.org, Applications → Personal access tokens, with
   `deposit:write` and `deposit:actions`. It is yours; nobody else sees it.
3. **Run `sh mint.sh`.** It validates, deposits and publishes. You get a DOI.

## What this kit is not

It is not a submission on your behalf. Nothing has been sent anywhere, and no token
here belongs to anyone but you.{
    " `author_verified` is `false` and the mint refuses to run until you set it, because only you can say the metadata about your work is right." if strict else ""}
{extra}"""


def write_index(outdir: str, entries: List[Dict[str, Any]]) -> str:
    path = os.path.join(outdir, "INDEX.json")
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(
            {"kit_version": KIT_VERSION, "kits": len(entries), "entries": entries},
            fh,
            indent=2,
            ensure_ascii=False,
        )
    return path


def group_records(
    records: Iterable[Dict[str, Any]],
    *,
    author_key: str = "author",
    url_key: str = "url",
    title_key: str = "title",
    digest_key: str = "sha256",
) -> Dict[str, List[Dict[str, Any]]]:
    """Group a flat record list by author, dropping unattributed rows.

    Returns {author: [artifact, ...]}. Unattributed records get no kit —
    a kit names an author, and inventing one is worse than omitting it.
    """
    out: Dict[str, List[Dict[str, Any]]] = {}
    for r in records:
        a = (r.get(author_key) or "").strip()
        if not a:
            continue
        out.setdefault(a, []).append(
            {
                "title": r.get(title_key) or r.get(url_key),
                "path": r.get(url_key),
                "sha256": r.get(digest_key),
            }
        )
    for v in out.values():
        v.sort(key=lambda x: (x.get("title") or ""))
    return out
