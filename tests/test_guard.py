"""Prove the guard: secrets, PII, IPR, integrity, clean-room, plagiarism, patents.

Offline, pure functions over metadata and small temp files.
"""
import os, sys, tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

CLEAN = {
    "title": "CHAKRA observatory kernel",
    "description": "An astronomical kernel with a byte-parity C99 twin. Source at "
                   "https://github.com/project-ilm/chakra and archived on Zenodo. "
                   "© 1993–2026 Abhishek Choudhary. All rights reserved.",
    "creators": [{"name": "Choudhary, Abhishek", "affiliation": "AyeAI"}],
    "keywords": ["astronomy", "calendars", "ephemeris"],
    "author_verified": True,
}


def kinds(res):
    return {f["kind"] for f in res["findings"]}


def test_clean_deposit_clears():
    from misty import guard
    res = guard.scan_deposit(CLEAN)
    assert res["clear"], res["findings"]
    assert res["counts"]["ERROR"] == 0
    print("  OK   clean deposit clears")


def test_secret_is_error_and_blocks():
    from misty import guard
    m = dict(CLEAN, description=CLEAN["description"] + " token: ghp_" + "a" * 36)
    res = guard.scan_deposit(m)
    assert not res["clear"], "a GitHub token did not block the mint"
    assert "secret" in kinds(res)
    # the token must not be echoed back in full
    s = next(f for f in res["findings"] if f["kind"] == "secret")["sample"]
    assert "…" in s and len(s) < 20, s
    print("  OK   secret: blocks the mint, sample is redacted")


def test_private_key_block_detected():
    from misty import guard
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "leaked.pem")
        open(p, "w").write("-----BEGIN RSA PRIVATE KEY-----\nMIIE...\n")
        res = guard.scan_deposit(CLEAN, files=[p])
        assert "secret" in kinds(res) and not res["clear"]
    print("  OK   private key block in a file is caught")


def test_third_party_email_warns_author_email_ok():
    from misty import guard
    m = dict(CLEAN, description=CLEAN["description"] + " contact someone@gmail.com")
    res = guard.scan_deposit(m)
    assert "privacy" in kinds(res)
    # an author domain address does not warn
    m2 = dict(CLEAN, description=CLEAN["description"] + " abhishek@ayeai.xyz")
    res2 = guard.scan_deposit(m2)
    assert "privacy" not in kinds(res2), "author-domain email wrongly flagged"
    print("  OK   privacy: third-party email warns, author domain does not")


def test_ipr_forbidden_string_and_home_path():
    from misty import guard
    m = dict(CLEAN, creators=[{"name": "X", "affiliation": "Independent Researcher"}])
    res = guard.scan_deposit(m)
    assert "ipr" in kinds(res) and not res["clear"]
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "notes.txt")
        open(p, "w").write("built under /home/abhishek-choudhary/work/secret/")
        res2 = guard.scan_deposit(CLEAN, files=[p])
        assert any(f["kind"] == "ipr" and "home path" in f["message"]
                   for f in res2["findings"]), res2["findings"]
    print("  OK   ipr: forbidden affiliation blocks; home path warns")


def test_integrity_requires_author_verification():
    from misty import guard
    m = dict(CLEAN); m.pop("author_verified")
    res = guard.scan_deposit(m)
    assert not res["clear"] and "integrity" in kinds(res)
    print("  OK   integrity: unverified metadata blocks the mint")


def test_cleanroom_expected_when_claiming_a_standard():
    from misty import guard
    m = dict(CLEAN, description="This implements the ISO 8601 standard for dates. "
                                "© 1993–2026 Abhishek Choudhary.")
    res = guard.scan_deposit(m)  # no CLEANROOM.md
    assert "cleanroom" in kinds(res)
    # supplying the record clears the clean-room warning
    with tempfile.TemporaryDirectory() as d:
        cr = os.path.join(d, "CLEANROOM.md")
        open(cr, "w").write("Re-implemented from the public ISO 8601 spec.")
        art = os.path.join(d, "code.txt"); open(art, "w").write("x")
        res2 = guard.scan_deposit(m, files=[cr, art])
        assert "cleanroom" not in kinds(res2), res2["findings"]
    print("  OK   cleanroom: expected when a standard is claimed, cleared by a record")


def test_plagiarism_flags_high_overlap():
    from misty import guard
    source = ("the quick brown fox jumps over the lazy dog while the sun sets "
              "slowly behind the distant mountains and the river flows on") * 3
    m = dict(CLEAN, description=source + " © 1993–2026 Abhishek Choudhary.")
    res = guard.scan_deposit(m, references=[source])
    assert not res["clear"] and "plagiarism" in kinds(res)
    # an unrelated reference does not trip it
    res2 = guard.scan_deposit(CLEAN, references=["completely different words entirely here"])
    assert "plagiarism" not in kinds(res2)
    print("  OK   plagiarism: high overlap blocks, unrelated text does not")


def test_patents_expected_when_describing_an_invention():
    from misty import guard
    m = dict(CLEAN, description="We present a novel method for ternary arithmetic, "
                                "previously unpublished. © 1993–2026 Abhishek Choudhary.")
    res = guard.scan_deposit(m)
    assert "patents" in kinds(res)
    # citing a patent clears it
    m2 = dict(m, patents=["IN 3033/CHE/2011"])
    assert "patents" not in kinds(guard.scan_deposit(m2))
    # marking it a defensive publication also clears it
    m3 = dict(m, defensive_publication=True)
    assert "patents" not in kinds(guard.scan_deposit(m3))
    print("  OK   patents: invention needs a patent ref or a defensive-pub flag")


if __name__ == "__main__":
    for fn in sorted(k for k in dict(globals()) if k.startswith("test_")):
        globals()[fn]()
    print("\n  9 passed")
