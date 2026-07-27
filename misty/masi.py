"""
misty.masi — MASI workflows: concept to persistent scholarly artifact.

© 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI.
SPDX-License-Identifier: GPL-3.0-or-later

MASI is Metadata-Assisted Scholarly Intelligence: the machine drafts, the human
stays responsible. This module is that stance as a state machine.

Every scholarly artifact travels a track. The tracks differ, but they share a
shape: a dated ledger, states that only advance through recorded evidence, and
gates that refuse to let a later stage run before an earlier one has happened.

The gates are the point. Three of them protect things that cannot be repaired
once broken:

  ETHICS   Human-subjects data collected before approval cannot be made
           approved afterwards. The approval must predate the collection.
  PREREG   A pre-registration is only worth the date on it. Its OTS proof must
           predate the first data-collection date, or it is a post-hoc plan
           wearing a registration's clothes.
  PATENT   A DOI is a dated public disclosure. In a first-to-file jurisdiction,
           minting before filing can destroy the novelty. Publication waits for
           the filing.

Tracks and states are DATA, not code — same reason walk's rules are data. A
venue with an unusual editorial ladder is a config change, not a patch.
"""

from __future__ import annotations

import datetime
import json
import os
import re
from typing import Any, Dict, List, Optional, Tuple

from .errors import MistyError

MASI_VERSION = "1.0"
ROOT = "masi"


def _today() -> str:
    return datetime.date.today().isoformat()


def _now() -> str:
    return datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _slug(s: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", s.lower())).strip("-")[:70]


# ---------------------------------------------------------------------------
# The tracks. `states` is ordered: a move is forward unless listed in `loops`.
# `evidence` names what must be on the ledger before a state may be entered.
# ---------------------------------------------------------------------------
TRACKS: Dict[str, Dict[str, Any]] = {
    "ethics": {
        "label": "IRB / ethics approval",
        "states": ["drafting", "submitted", "clarifications", "approved",
                   "amendment", "renewed", "expired", "closed", "rejected"],
        "loops": ["clarifications", "amendment", "renewed"],
        "terminal": ["closed", "rejected", "expired"],
        "evidence": {"approved": ["approval_ref", "approved_on", "expires_on"]},
        "note": "Approval carries a reference and an expiry. Both are recorded, "
                "because an expired approval is not an approval.",
    },
    "prereg": {
        "label": "pre-registration",
        "states": ["drafting", "stamped", "registered", "collecting",
                   "deviation", "complete", "withdrawn"],
        "loops": ["deviation"],
        "terminal": ["complete", "withdrawn"],
        "evidence": {"stamped": ["stamp_file", "stamped_on"],
                     "collecting": ["collection_started_on"]},
        "note": "The OTS stamp on the plan is the whole instrument. Deviations "
                "are recorded, never edited into the original.",
    },
    "paper": {
        "label": "manuscript",
        "states": ["drafting", "stamped", "internal-review", "revising", "ready"],
        "loops": ["revising", "internal-review"],
        "terminal": ["ready"],
        "evidence": {"stamped": ["stamp_file", "stamped_on"]},
        "note": "Pre-venue. Hands off to journal, conference or chapter.",
    },
    "journal": {
        "label": "journal article",
        "states": ["prepared", "submitted", "desk-check", "under-review",
                   "reviews-received", "major-revision", "minor-revision",
                   "resubmitted", "accepted", "copyedit", "proof", "published",
                   "rejected", "withdrawn"],
        "loops": ["major-revision", "minor-revision", "resubmitted",
                  "under-review", "reviews-received", "copyedit", "proof"],
        "terminal": ["published", "rejected", "withdrawn"],
        "evidence": {"submitted": ["venue", "submitted_on"],
                     "accepted": ["accepted_on"],
                     "published": ["published_on"]},
        "review": True,
        "note": "Editorial ladder. Acceptance requires at least one recorded "
                "review round — an accept with no reviews on the ledger is a "
                "record of nothing.",
    },
    "conference": {
        "label": "conference paper or poster",
        "states": ["prepared", "abstract-submitted", "abstract-accepted",
                   "full-submitted", "under-review", "reviews-received",
                   "rebuttal", "accepted", "camera-ready", "presented",
                   "proceedings-published", "rejected", "withdrawn"],
        "loops": ["under-review", "reviews-received", "rebuttal"],
        "terminal": ["proceedings-published", "presented", "rejected", "withdrawn"],
        "evidence": {"abstract-submitted": ["venue", "submitted_on"],
                     "accepted": ["accepted_on"],
                     "presented": ["presented_on", "presentation_kind"]},
        "review": True,
        "note": "Two submission rounds and a rebuttal window, which journals "
                "do not have. presentation_kind is talk or poster.",
    },
    "chapter": {
        "label": "book chapter",
        "states": ["proposed", "invited", "drafting", "submitted",
                   "editor-review", "revising", "final", "in-production",
                   "published", "declined", "withdrawn"],
        "loops": ["editor-review", "revising"],
        "terminal": ["published", "declined", "withdrawn"],
        "evidence": {"submitted": ["volume_title", "editor", "submitted_on"],
                     "published": ["published_on"]},
        "review": True,
        "note": "Editor-led rather than peer-panel-led, and usually invited. "
                "The volume and its editor are recorded from the start.",
    },
    "patent": {
        "label": "patent matter",
        "states": ["drafting", "disclosed", "filed", "published",
                   "office-action", "granted", "abandoned"],
        "loops": ["office-action"],
        "terminal": ["granted", "abandoned"],
        "evidence": {"disclosed": ["stamp_file", "stamped_on"],
                     "filed": ["application_no", "jurisdiction", "filed_on"]},
        "note": "Mirrors patent_track.sh and stops where it stops: filing is a "
                "human and counsel decision, never a script's.",
    },
}

REVIEW_DECISIONS = ["accept", "minor-revision", "major-revision", "reject",
                    "desk-reject", "conditional-accept"]


# ---------------------------------------------------------------------------
# Ledger
# ---------------------------------------------------------------------------
def path_for(slug: str, root: str = ROOT) -> str:
    return os.path.join(root, slug, "matter.json")


def load(slug: str, root: str = ROOT) -> Dict[str, Any]:
    p = path_for(slug, root)
    if not os.path.exists(p):
        raise MistyError(f"no MASI matter {slug!r} — `misty masi new {slug} --track ...` first")
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def save(m: Dict[str, Any], root: str = ROOT) -> str:
    p = path_for(m["slug"], root)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(m, fh, indent=2, ensure_ascii=False)
    return p


def new(slug: str, track: str, title: str = "", root: str = ROOT,
        links: Optional[List[str]] = None) -> Dict[str, Any]:
    if track not in TRACKS:
        raise MistyError(f"unknown track {track!r}; one of: {', '.join(sorted(TRACKS))}")
    slug = _slug(slug)
    if os.path.exists(path_for(slug, root)):
        raise MistyError(f"MASI matter {slug!r} already exists")
    m = {
        "masi_version": MASI_VERSION,
        "slug": slug,
        "track": track,
        "title": title or slug,
        "state": TRACKS[track]["states"][0],
        "created": _now(),
        "links": links or [],
        "facts": {},
        "reviews": [],
        "history": [{"at": _now(), "state": TRACKS[track]["states"][0], "note": "created"}],
    }
    save(m, root)
    return m


def set_facts(m: Dict[str, Any], pairs: List[str]) -> Dict[str, Any]:
    for kv in pairs:
        if "=" not in kv:
            raise MistyError(f"--set expects key=value, got {kv!r}")
        k, v = kv.split("=", 1)
        m["facts"][k.strip()] = v.strip()
    return m


def advance(m: Dict[str, Any], state: str, note: str = "",
            root: str = ROOT, force: bool = False) -> Dict[str, Any]:
    spec = TRACKS[m["track"]]
    if state not in spec["states"]:
        raise MistyError(
            f"{state!r} is not a state of track {m['track']!r}; one of: "
            + ", ".join(spec["states"]))
    if m["state"] in spec["terminal"] and not force:
        raise MistyError(f"{m['slug']} is terminal at {m['state']!r} — --force to override")

    if spec.get("review") and state == "accepted" and not m["reviews"] and not force:
        raise MistyError(
            f"{m['slug']}: acceptance with no review round recorded. Add the "
            f"decision that was actually made:\n"
            f"  misty masi review {m['slug']} --round 1 --decision accept")

    missing = [k for k in spec.get("evidence", {}).get(state, []) if k not in m["facts"]]
    if missing and not force:
        raise MistyError(
            f"state {state!r} needs evidence on the ledger first: "
            + ", ".join(missing)
            + f"\n  misty masi set {m['slug']} " + " ".join(f"{k}=..." for k in missing))

    cur_i = spec["states"].index(m["state"])
    new_i = spec["states"].index(state)
    if new_i < cur_i and state not in spec["loops"] and not force:
        raise MistyError(
            f"{state!r} is behind {m['state']!r} and is not a loop state — --force to override")

    m["state"] = state
    m["history"].append({"at": _now(), "state": state, "note": note or ""})
    save(m, root)
    return m


def add_review(m: Dict[str, Any], round_no: int, decision: str, reviewer: str = "",
               note: str = "", received_on: str = "", root: str = ROOT) -> Dict[str, Any]:
    if not TRACKS[m["track"]].get("review"):
        raise MistyError(f"track {m['track']!r} has no peer-review stage")
    if decision not in REVIEW_DECISIONS:
        raise MistyError(f"decision must be one of: {', '.join(REVIEW_DECISIONS)}")
    m["reviews"].append({
        "round": int(round_no),
        "decision": decision,
        "reviewer": reviewer or "(anonymous)",
        "received_on": received_on or _today(),
        "note": note,
        "at": _now(),
    })
    m["history"].append({"at": _now(), "state": m["state"],
                         "note": f"review r{round_no}: {decision}"})
    save(m, root)
    return m


# ---------------------------------------------------------------------------
# Gates — the interlocks between tracks. Each returns (ok, severity, message).
# ---------------------------------------------------------------------------
def _date(m: Dict[str, Any], key: str) -> Optional[datetime.date]:
    v = m["facts"].get(key)
    if not v:
        return None
    try:
        return datetime.date.fromisoformat(v[:10])
    except ValueError:
        return None


def _linked(m: Dict[str, Any], root: str) -> List[Dict[str, Any]]:
    out = []
    for s in m.get("links", []):
        try:
            out.append(load(_slug(s), root))
        except MistyError:
            pass
    return out


def gates(m: Dict[str, Any], root: str = ROOT) -> List[Tuple[str, str, str]]:
    """Returns [(id, severity, message)] — severity is ok|WARN|ERROR."""
    res: List[Tuple[str, str, str]] = []
    linked = _linked(m, root)
    by_track = {}
    for l in linked:
        by_track.setdefault(l["track"], []).append(l)

    # G1 — human subjects need approval before collection
    if m["facts"].get("human_subjects", "").lower() in ("1", "true", "yes"):
        eth = by_track.get("ethics", [])
        if not eth:
            res.append(("G1", "ERROR",
                        "human_subjects is set but no ethics matter is linked "
                        "(--link <ethics-slug>)"))
        else:
            e = eth[0]
            if e["state"] != "approved" and e["state"] not in ("renewed", "amendment"):
                res.append(("G1", "ERROR",
                            f"ethics matter {e['slug']} is {e['state']!r}, not approved"))
            else:
                ap, st = _date(e, "approved_on"), _date(m, "collection_started_on")
                exp = _date(e, "expires_on")
                if ap and st and st < ap:
                    res.append(("G1", "ERROR",
                                f"collection began {st} but approval is dated {ap} — "
                                "an approval cannot be applied backwards"))
                elif ap and st:
                    res.append(("G1", "ok", f"approval {ap} precedes collection {st}"))
                if exp and exp < datetime.date.today() and m["state"] not in ("complete",):
                    res.append(("G1", "WARN",
                                f"ethics approval expired {exp} — renew before further collection"))

    # G2 — a pre-registration is only worth its date
    if m["track"] == "prereg":
        stamped, started = _date(m, "stamped_on"), _date(m, "collection_started_on")
        if started and not stamped:
            res.append(("G2", "ERROR",
                        "collection has a start date but the plan was never stamped"))
        elif stamped and started:
            if stamped > started:
                res.append(("G2", "ERROR",
                            f"plan stamped {stamped}, collection began {started} — "
                            "this is a post-hoc plan, not a pre-registration"))
            else:
                res.append(("G2", "ok", f"plan stamped {stamped} before collection {started}"))
        sf = m["facts"].get("stamp_file")
        if sf and not os.path.exists(sf + ".ots") and not os.path.exists(sf):
            res.append(("G2", "WARN", f"stamp_file {sf} is not on disk to re-verify"))

    # G3 — a DOI is a dated public disclosure
    pat = by_track.get("patent", [])
    if pat and m["track"] != "patent":
        unfiled = [p for p in pat
                   if p["state"] in ("drafting", "disclosed")]
        if unfiled:
            names = ", ".join(p["slug"] for p in unfiled)
            res.append(("G3", "ERROR",
                        f"linked patent matter not yet filed ({names}). Minting a DOI "
                        "publishes the invention; in a first-to-file jurisdiction that "
                        "can end the novelty. File first, or record a deliberate "
                        "defensive disclosure: --set defensive_publication=true"))
        else:
            res.append(("G3", "ok", "linked patent matters are filed or beyond"))
    if m["facts"].get("defensive_publication", "").lower() in ("1", "true", "yes"):
        res.append(("G3", "WARN",
                    "defensive_publication is asserted — publication will bar a later "
                    "patent on this disclosure. Recorded as deliberate."))

    # G4 — acceptance needs a recorded review round
    if TRACKS[m["track"]].get("review"):
        if m["state"] in ("accepted", "camera-ready", "copyedit", "proof",
                          "published", "proceedings-published", "in-production"):
            if not m["reviews"]:
                res.append(("G4", "ERROR",
                            f"{m['state']!r} reached with no review round on the ledger"))
            else:
                last = m["reviews"][-1]
                res.append(("G4", "ok",
                            f"{len(m['reviews'])} review round(s); last decision "
                            f"{last['decision']!r}"))

    # G5 — a prereg'd study should say what happened to its plan
    if m["track"] in ("journal", "conference", "chapter"):
        pre = by_track.get("prereg", [])
        if pre and not any(p["state"] in ("complete", "collecting", "registered") for p in pre):
            res.append(("G5", "WARN",
                        "a pre-registration is linked but never reached registered"))
        if m["facts"].get("human_subjects", "").lower() in ("1", "true", "yes") and not pre:
            res.append(("G5", "WARN",
                        "human-subjects work with no linked pre-registration"))

    if not res:
        res.append(("--", "ok", "no gate applies to this matter yet"))
    return res


def mintable(m: Dict[str, Any], root: str = ROOT) -> Tuple[bool, List[str]]:
    """May this matter be minted? Errors block; warnings do not."""
    errs = [f"{i}: {msg}" for i, sev, msg in gates(m, root) if sev == "ERROR"]
    return (not errs), errs


def render(m: Dict[str, Any], root: str = ROOT) -> str:
    spec = TRACKS[m["track"]]
    out = [f"{m['slug']}  [{m['track']}] {spec['label']}",
           f"  title   : {m['title']}",
           f"  state   : {m['state']}"]
    if m["links"]:
        out.append("  links   : " + ", ".join(m["links"]))
    if m["facts"]:
        out.append("  facts   : " + ", ".join(f"{k}={v}" for k, v in sorted(m["facts"].items())))
    if m["reviews"]:
        out.append("  reviews :")
        for r in m["reviews"]:
            out.append(f"    r{r['round']} {r['received_on']} {r['decision']:<18} {r['reviewer']}")
    out.append("  gates   :")
    for i, sev, msg in gates(m, root):
        mark = {"ok": "ok  ", "WARN": "WARN", "ERROR": "FAIL"}[sev]
        out.append(f"    {mark} {i:<3} {msg}")
    out.append("  history :")
    for h in m["history"][-6:]:
        out.append(f"    {h['at']}  {h['state']:<22} {h['note']}")
    return "\n".join(out)


def all_matters(root: str = ROOT) -> List[Dict[str, Any]]:
    if not os.path.isdir(root):
        return []
    out = []
    for s in sorted(os.listdir(root)):
        p = path_for(s, root)
        if os.path.exists(p):
            with open(p, encoding="utf-8") as fh:
                out.append(json.load(fh))
    return out
