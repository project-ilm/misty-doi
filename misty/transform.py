"""Derive every downstream metadata format from the canonical Misty record.

Targets:
  - Zenodo deposit metadata  (the {"metadata": {...}} body)
  - DataCite 4.x JSON
  - codemeta.json (schema.org SoftwareSourceCode)
  - CITATION.cff (CFF 1.2.0, emitted as valid YAML)

All functions are pure: canonical dict in, dict (or str for CFF) out.
"""

from __future__ import annotations

import datetime
import re
from typing import Any, Dict, List

# Zenodo license id -> SPDX identifier (extend as needed).
_SPDX = {
    "gpl-3.0": "GPL-3.0-or-later",
    "gpl-3.0-only": "GPL-3.0-only",
    "gpl-2.0": "GPL-2.0-or-later",
    "lgpl-3.0": "LGPL-3.0-or-later",
    "agpl-3.0": "AGPL-3.0-or-later",
    "apache-2.0": "Apache-2.0",
    "mit": "MIT",
    "bsd-3-clause": "BSD-3-Clause",
    "bsd-2-clause": "BSD-2-Clause",
    "cc-by-4.0": "CC-BY-4.0",
    "cc-by-sa-4.0": "CC-BY-SA-4.0",
    "cc-by-nc-4.0": "CC-BY-NC-4.0",
    "cc0-1.0": "CC0-1.0",
}

# DataCite resourceTypeGeneral mapping from Zenodo upload_type.
_DATACITE_TYPE = {
    "software": "Software",
    "dataset": "Dataset",
    "publication": "Text",
    "poster": "Text",
    "presentation": "Text",
    "image": "Image",
    "video": "Audiovisual",
    "workflow": "Workflow",
    "lesson": "Text",
    "physicalobject": "PhysicalObject",
    "other": "Other",
}

_TAG_RE = re.compile(r"<[^>]+>")


def spdx(zenodo_license: str) -> str:
    return _SPDX.get((zenodo_license or "").lower(), zenodo_license)


def strip_html(text: str) -> str:
    return _TAG_RE.sub("", text or "").strip()


def _split_name(name: str):
    """'Family, Given' -> ('Family', 'Given'); fall back gracefully."""
    if ", " in name:
        fam, giv = name.split(", ", 1)
        return fam.strip(), giv.strip()
    return name.strip(), ""


# --------------------------------------------------------------------------- #
# Zenodo
# --------------------------------------------------------------------------- #
_ZENODO_KEYS = {
    "title", "upload_type", "publication_type", "description", "creators",
    "license", "access_right", "keywords", "communities", "grants",
    "related_identifiers", "references", "dates", "language", "version",
    "notes", "embargo_date", "access_conditions",
}


def to_zenodo(m: Dict[str, Any]) -> Dict[str, Any]:
    """Build the inner Zenodo metadata object (not yet wrapped)."""
    out = {k: v for k, v in m.items() if k in _ZENODO_KEYS and v not in (None, [], "")}
    out["creators"] = [
        {k: c[k] for k in ("name", "affiliation", "orcid", "gnd") if c.get(k)}
        for c in m["creators"]
    ]
    return out


def to_zenodo_body(m: Dict[str, Any]) -> Dict[str, Any]:
    """The exact JSON body sent to PUT /deposit/depositions/{id}."""
    return {"metadata": to_zenodo(m)}


# --------------------------------------------------------------------------- #
# codemeta
# --------------------------------------------------------------------------- #
def to_codemeta(m: Dict[str, Any]) -> Dict[str, Any]:
    authors = []
    for c in m["creators"]:
        fam, giv = _split_name(c["name"])
        a: Dict[str, Any] = {"@type": "Person", "familyName": fam}
        if giv:
            a["givenName"] = giv
        if c.get("orcid"):
            a["@id"] = f"https://orcid.org/{c['orcid']}"
        if c.get("affiliation"):
            a["affiliation"] = {"@type": "Organization", "name": c["affiliation"]}
        authors.append(a)

    cm: Dict[str, Any] = {
        "@context": "https://doi.org/10.5063/schema/codemeta-2.0",
        "@type": "SoftwareSourceCode",
        "name": m["title"],
        "description": m["description"],
        "version": m.get("version"),
        "license": f"https://spdx.org/licenses/{spdx(m['license'])}",
        "keywords": m.get("keywords") or None,
        "author": authors,
        "dateModified": datetime.date.today().isoformat(),
        "programmingLanguage": m.get("programming_language") or None,
        "codeRepository": m.get("repository") or None,
    }
    if m.get("doi"):
        cm["identifier"] = f"https://doi.org/{m['doi']}"
    return {k: v for k, v in cm.items() if v not in (None, [], "")}


# --------------------------------------------------------------------------- #
# DataCite 4.x
# --------------------------------------------------------------------------- #
def to_datacite(m: Dict[str, Any]) -> Dict[str, Any]:
    creators = []
    for c in m["creators"]:
        fam, giv = _split_name(c["name"])
        entry: Dict[str, Any] = {
            "name": c["name"],
            "nameType": "Personal",
            "givenName": giv or None,
            "familyName": fam,
        }
        if c.get("affiliation"):
            entry["affiliation"] = [{"name": c["affiliation"]}]
        if c.get("orcid"):
            entry["nameIdentifiers"] = [{
                "nameIdentifier": f"https://orcid.org/{c['orcid']}",
                "nameIdentifierScheme": "ORCID",
                "schemeUri": "https://orcid.org",
            }]
        creators.append({k: v for k, v in entry.items() if v not in (None, [])})

    year = str(datetime.date.today().year)
    for d in m.get("dates", []):
        if d.get("date"):
            year = str(d["date"])[:4]
            break

    dc: Dict[str, Any] = {
        "schemaVersion": "http://datacite.org/schema/kernel-4",
        "types": {
            "resourceTypeGeneral": _DATACITE_TYPE.get(m["upload_type"], "Other"),
            "resourceType": m.get("publication_type", m["upload_type"]),
        },
        "titles": [{"title": m["title"]}],
        "creators": creators,
        "publisher": "Zenodo",
        "publicationYear": year,
        "subjects": [{"subject": k} for k in m.get("keywords", [])] or None,
        "version": m.get("version"),
        "descriptions": [{
            "description": strip_html(m["description"]),
            "descriptionType": "Abstract",
        }],
        "rightsList": [{
            "rights": spdx(m["license"]),
            "rightsIdentifier": spdx(m["license"]),
            "rightsIdentifierScheme": "SPDX",
        }],
        "language": m.get("language", "eng"),
    }
    if m.get("doi"):
        dc["identifiers"] = [{"identifier": m["doi"], "identifierType": "DOI"}]
    if m.get("related_identifiers"):
        dc["relatedIdentifiers"] = [
            {
                "relatedIdentifier": r.get("identifier"),
                "relationType": (r.get("relation", "")[:1].upper() + r.get("relation", "")[1:]),
                "relatedIdentifierType": "URL" if str(r.get("identifier", "")).startswith("http") else "DOI",
            }
            for r in m["related_identifiers"]
        ]
    return {k: v for k, v in dc.items() if v not in (None, [])}


# --------------------------------------------------------------------------- #
# CITATION.cff (CFF 1.2.0) — emitted as valid YAML with no PyYAML dependency
# --------------------------------------------------------------------------- #
def to_cff_dict(m: Dict[str, Any]) -> Dict[str, Any]:
    authors: List[Dict[str, Any]] = []
    for c in m["creators"]:
        fam, giv = _split_name(c["name"])
        a: Dict[str, Any] = {"family-names": fam}
        if giv:
            a["given-names"] = giv
        if c.get("orcid"):
            a["orcid"] = f"https://orcid.org/{c['orcid']}"
        if c.get("affiliation"):
            a["affiliation"] = c["affiliation"]
        authors.append(a)

    cff: Dict[str, Any] = {
        "cff-version": "1.2.0",
        "message": "If you use this software, please cite it as below.",
        "title": m["title"],
        "version": m.get("version"),
        "abstract": strip_html(m["description"]),
        "authors": authors,
        "license": spdx(m["license"]),
        "keywords": m.get("keywords") or None,
    }
    if m.get("doi"):
        cff["doi"] = m["doi"]
    if m.get("repository"):
        cff["repository-code"] = m["repository"]
    return {k: v for k, v in cff.items() if v not in (None, [], "")}


def to_cff(m: Dict[str, Any]) -> str:
    """Serialize the CFF dict to a valid YAML 1.2 string (block style)."""
    return _yaml_dump(to_cff_dict(m))


# --- minimal, correct YAML emitter for the bounded CFF structure ----------- #
def _yaml_scalar(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    s = str(v)
    # Always double-quote strings to stay safe across colons, hashes, etc.
    return '"' + s.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n") + '"'


def _yaml_dump(obj: Any, indent: int = 0) -> str:
    pad = "  " * indent
    lines: List[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if isinstance(v, dict):
                lines.append(f"{pad}{k}:")
                lines.append(_yaml_dump(v, indent + 1))
            elif isinstance(v, list):
                lines.append(f"{pad}{k}:")
                for item in v:
                    if isinstance(item, (dict, list)):
                        block = _yaml_dump(item, indent + 2).split("\n")
                        block[0] = "  " * (indent + 1) + "- " + block[0].lstrip()
                        lines.extend(block)
                    else:
                        lines.append("  " * (indent + 1) + f"- {_yaml_scalar(item)}")
            else:
                lines.append(f"{pad}{k}: {_yaml_scalar(v)}")
    else:
        lines.append(f"{pad}{_yaml_scalar(obj)}")
    return "\n".join(l for l in lines if l.strip())


# Registry used by package builder: filename -> (callable, is_json)
TARGETS = {
    "zenodo.json": (to_zenodo_body, True),
    "datacite.json": (to_datacite, True),
    "codemeta.json": (to_codemeta, True),
    "CITATION.cff": (to_cff, False),
}
