#!/usr/bin/env python3
"""Prove every walk rule bites. Offline — fixtures, no network, no mock.

Each case is a record built to violate exactly one rule. If the walk does not
report that rule for that record, the rule is decorative and the test fails.
"""
import json, os, subprocess, sys, tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PKG = os.path.dirname(HERE)
sys.path.insert(0, PKG)

RULES = {
    "affiliation_must_be": "AyeAI",
    "forbidden_strings": ["Independent Researcher", "kaivalyikagi.org"],
    "expected_orcid": "0009-0002-0684-8320",
    "copyright_contains": "\u00a9 1993\u20132026 Abhishek Choudhary",
    "known_facts": {"PEDLER": {"publication_date": "2001-11-01"}},
}

GOOD_CREATOR = {"name": "Choudhary, Abhishek", "affiliation": "AyeAI",
                "orcid": "0009-0002-0684-8320"}
GOOD_DESC = ("A real description long enough to pass the floor. "
             "\u00a9 1993\u20132026 Abhishek Choudhary. All rights reserved.")


def rec(rid, **over):
    m = {"title": over.pop("title", "Thing %s" % rid), "version": "1.0.0",
         "description": GOOD_DESC, "license": "gpl-3.0",
         "creators": [dict(GOOD_CREATOR)], "related_identifiers": [],
         "publication_date": "2026-01-01"}
    m.update(over.pop("metadata", {}))
    r = {"id": rid, "state": "done", "submitted": True,
         "doi": "10.5281/zenodo.%d" % rid, "conceptdoi": "10.5281/zenodo.%d" % (rid - 500),
         "metadata": m, "files": [{"id": "f1", "key": "a.zip"}]}
    r.update(over)
    return r


CASES = [
    ("clean record produces no findings", rec(1001), None),
    ("wrong affiliation",
     rec(1002, metadata={"creators": [dict(GOOD_CREATOR, affiliation="Independent Researcher")]}),
     "affiliation must be"),
    ("forbidden string anywhere in the record",
     rec(1003, metadata={"description": GOOD_DESC + " see kaivalyikagi.org"}),
     "forbidden string"),
    ("wrong ORCID",
     rec(1004, metadata={"creators": [dict(GOOD_CREATOR, orcid="0000-0000-0000-0000")]}),
     "ORCID is not"),
    ("missing ORCID",
     rec(1005, metadata={"creators": [{"name": "X", "affiliation": "AyeAI"}]}),
     "no ORCID"),
    ("no version string", rec(1006, metadata={"version": ""}), "no version string"),
    ("no license", rec(1007, metadata={"license": None}), "no license"),
    ("empty description", rec(1008, metadata={"description": ""}), "empty description"),
    ("description missing the copyright line",
     rec(1009, metadata={"description": "A description long enough to clear the floor easily."}),
     "does not carry"),
    ("published with no DOI", rec(1010, doi=None, metadata={"doi": None}), "carries no DOI"),
    ("no concept DOI", rec(1011, conceptdoi=None), "no concept DOI"),
    ("self-referential related identifier",
     rec(1012, metadata={"related_identifiers": [
         {"identifier": "https://doi.org/10.5281/zenodo.1012", "relation": "isSupplementTo"}]}),
     "its own DOI"),
    ("published with no files", rec(1013, files=[]), "no files"),
    ("no creators", rec(1014, metadata={"creators": []}), "no creators"),
    ("author-asserted date contradicted",
     rec(1015, title="PEDLER", metadata={"publication_date": "2011-01-01"}),
     "author-asserted date"),
    ("unpublished draft is noted, not judged",
     rec(1016, state="unsubmitted", submitted=False, doi=None), "unpublished draft"),
]


def main():
    from misty import audit
    rules = audit.load_rules(None)
    rules.update(RULES)

    passed = failed = 0
    for name, record, want in CASES:
        findings = audit.check_record(record, rules)
        msgs = " | ".join(f["message"] for f in findings)
        if want is None:
            ok = not [f for f in findings if f["severity"] in ("ERROR", "WARN")]
        else:
            ok = want in msgs
        print("  %-4s %-46s %s" % ("OK" if ok else "FAIL", name,
                                   "" if ok else ("got: " + (msgs or "(nothing)"))[:90]))
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)

    # estate-level: the split lineage
    split = [rec(2001, title="Same Thing"), rec(2002, title="Same Thing")]
    split[1]["conceptdoi"] = "10.5281/zenodo.9999"
    f = audit.check_estate(split, rules)
    ok = any("separate concept" in x["message"] for x in f)
    print("  %-4s %-46s" % ("OK" if ok else "FAIL", "split lineage detected across records"))
    passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)

    # a real lineage (one concept, two versions) must NOT be flagged
    fine = [rec(3001, title="Proper Lineage"), rec(3002, title="Proper Lineage")]
    fine[1]["conceptdoi"] = fine[0]["conceptdoi"]
    ok = not [x for x in audit.check_estate(fine, rules) if "separate concept" in x["message"]]
    print("  %-4s %-46s" % ("OK" if ok else "FAIL", "a genuine version lineage is not flagged"))
    passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)

    # repo scan: a DOI present in a repo vs one that is nowhere
    with tempfile.TemporaryDirectory() as d:
        os.makedirs(os.path.join(d, "sub"))
        open(os.path.join(d, "sub", "CITATION.cff"), "w").write("doi: 10.5281/zenodo.4001\n")
        idx = audit.scan_repo_dois([d])
        ok = "10.5281/zenodo.4001" in idx
        print("  %-4s %-46s" % ("OK" if ok else "FAIL", "repo DOI scan finds a recorded DOI"))
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)

        report = audit.walk([rec(4501), rec(4001)], rules, repo_roots=[d])
        unrec = [f for f in report["findings"] if "not recorded anywhere" in f["message"]]
        ok = len(unrec) == 1 and unrec[0]["doi"] == "10.5281/zenodo.4501"
        print("  %-4s %-46s" % ("OK" if ok else "FAIL", "unrecorded DOI flagged, recorded one is not"))
        passed, failed = (passed + 1, failed) if ok else (passed, failed + 1)

    print("\n  %d passed, %d failed" % (passed, failed))
    return 1 if failed else 0


def test_walk_rules_all_bite():
    assert main() == 0


if __name__ == "__main__":
    sys.exit(main())
