"""Prove harvest's three jobs: dedupe by content, score write-ups, propose links.

Offline. No network, no mock — these are pure functions over records and files.
"""
import json, os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

THIN = "A tool."
FULL = ("We address the problem that scholarly software has no atomic provenance "
        "layer. Our method registers a cryptographic digest at arbitrary granularity "
        "using OpenTimestamps, and the result is a browser-first registrar requiring "
        "no backend. Source and build instructions are at https://github.com/project-ilm/tok-doi "
        "so every claim here can be re-run independently by a reader. "
        "This design contributes a reproducible substrate for citation at sub-artifact "
        "granularity, which conventional DOI minting cannot express. " * 2)


def rec(rid, title, desc, keywords=(), related=(), version="1.0.0", license="gpl-3.0"):
    return {"id": rid, "state": "done", "submitted": True,
            "doi": "10.5281/zenodo.%d" % rid,
            "conceptdoi": "10.5281/zenodo.%d" % (rid - 1),
            "metadata": {"title": title, "description": desc, "version": version,
                         "license": license, "keywords": list(keywords),
                         "related_identifiers": list(related),
                         "creators": [{"name": "Choudhary, Abhishek", "affiliation": "AyeAI"}]},
            "files": [{"id": "f1", "key": "a.zip"}]}


def test_dedupe_hardlinks_identical_payloads():
    from misty import harvest
    with tempfile.TemporaryDirectory() as d:
        for rid in ("1001", "1002", "1003"):
            os.makedirs(os.path.join(d, rid))
            open(os.path.join(d, rid, "payload.bin"), "wb").write(b"identical bytes" * 5000)
        os.makedirs(os.path.join(d, "1004"))
        open(os.path.join(d, "1004", "payload.bin"), "wb").write(b"different" * 5000)

        before = sum(os.path.getsize(os.path.join(dp, f))
                     for dp, _, fs in os.walk(d) for f in fs)
        out = harvest.dedupe(d, link=True)
        assert out["duplicate_groups"] == 1, out
        assert out["bytes_reclaimed"] > 0, out
        inos = {os.stat(os.path.join(d, r, "payload.bin")).st_ino
                for r in ("1001", "1002", "1003")}
        assert len(inos) == 1, "the three identical payloads are not one inode"
        assert os.stat(os.path.join(d, "1004", "payload.bin")).st_ino not in inos
        # content survives the relink
        assert open(os.path.join(d, "1002", "payload.bin"), "rb").read(15) == b"identical bytes"
        print("  OK   dedupe: 3 copies -> 1 inode, %d bytes reclaimed of %d"
              % (out["bytes_reclaimed"], before))


def test_rubric_separates_thin_from_full():
    from misty import harvest
    rows = harvest.assess([
        rec(2001, "Thin Record", THIN),
        rec(2002, "Full Record", FULL, keywords=("provenance", "timestamps", "doi"),
            related=({"identifier": "10.5281/zenodo.9", "relation": "references"},)),
    ])
    thin = [r for r in rows if r["id"] == 2001][0]
    full = [r for r in rows if r["id"] == 2002][0]
    assert thin["score"] < full["score"], rows
    assert full["score"] == full["of"], full["missing"]
    assert "a substantive abstract (>= 600 characters)" in thin["missing"]
    assert rows[0]["id"] == 2001, "worst write-up must sort first"
    print("  OK   rubric: thin %d/%d, full %d/%d, worst sorts first"
          % (thin["score"], thin["of"], full["score"], full["of"]))


def test_crossref_proposes_related_and_skips_existing():
    from misty import harvest
    a = rec(3001, "CHAKRA temporal cycle observatory ephemeris",
            FULL, keywords=("ephemeris", "calendar", "observatory"))
    b = rec(3002, "CHAKRA ephemeris observatory calendar bindings",
            FULL, keywords=("ephemeris", "calendar", "observatory"))
    c = rec(3003, "Entirely unrelated legal instrument",
            FULL, keywords=("proclamation", "equity", "constitution"))
    props = harvest.propose_links([a, b, c], min_shared=3)
    pairs = {(p["from"], p["to"]) for p in props}
    assert (3001, 3002) in pairs, props
    assert not any(3003 in pr for pr in pairs), "unrelated record was linked"
    assert all(p["relation"] == "references" for p in props), "stronger relation asserted"

    # an existing link must not be proposed again
    a2 = rec(3001, a["metadata"]["title"], FULL,
             keywords=a["metadata"]["keywords"],
             related=({"identifier": "10.5281/zenodo.3002", "relation": "references"},))
    again = harvest.propose_links([a2, b, c], min_shared=3)
    assert (3001, 3002) not in {(p["from"], p["to"]) for p in again}, again
    print("  OK   crossref: related pair proposed, unrelated skipped, existing not repeated")


def test_patch_is_inert():
    from misty import harvest
    props = harvest.propose_links(
        [rec(4001, "alpha beta gamma delta", FULL, keywords=("alpha", "beta", "gamma")),
         rec(4002, "alpha beta gamma epsilon", FULL, keywords=("alpha", "beta", "gamma"))],
        min_shared=3)
    patch = harvest.patch_for(props)
    assert "_note" in patch and "nothing here has been applied" in patch["_note"].lower()
    assert patch["records"], patch
    for entries in patch["records"].values():
        for e in entries:
            assert e["relation"] == "references"
            assert e["_because"].startswith("shares:")
    print("  OK   patch: proposals only, every entry carries its reason")


if __name__ == "__main__":
    test_dedupe_hardlinks_identical_payloads()
    test_rubric_separates_thin_from_full()
    test_crossref_proposes_related_and_skips_existing()
    test_patch_is_inert()
    print("\n  4 passed")
