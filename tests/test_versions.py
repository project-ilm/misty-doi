# © 1993–2026 Abhishek Choudhary. All rights reserved. AyeAI.
# SPDX-License-Identifier: GPL-3.0-or-later
"""The update features, against the local Zenodo stand-in: newversion and update.

Live Zenodo is never contacted: a mint cannot be undone and a test that mints cannot
run twice. tests/mock_zenodo.py keeps Zenodo's rules that matter here: only the latest
published version may be versioned, one open version draft per concept, a version
draft inherits files, metadata is replaced on PUT, and an edit keeps its DOI.
"""
import json
import os
import socket
import subprocess
import sys
import time
import unittest
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
META = {
    "title": "Versioning test record", "version": "1.0.0", "upload_type": "software",
    "description": "A record for the version tests. © 1993–2026 Abhishek Choudhary. All rights reserved.",
    "license": "gpl-3.0", "access_right": "open",
    "creators": [{"name": "Choudhary, Abhishek", "affiliation": "AyeAI", "orcid": "0009-0002-0684-8320"}],
    "author_verified": True,
}


def _port():
    s = socket.socket(); s.bind(("127.0.0.1", 0)); p = s.getsockname()[1]; s.close(); return p


class Versions(unittest.TestCase):
    rdm = "0"

    @classmethod
    def setUpClass(cls):
        cls.work = os.path.join(ROOT, ".test-versions-" + cls.__name__)
        os.makedirs(cls.work, exist_ok=True)
        cls.port = _port()
        env = dict(os.environ, MOCK_RDM_SHAPE=cls.rdm)
        cls.mock = subprocess.Popen([sys.executable, os.path.join(HERE, "mock_zenodo.py"), str(cls.port)],
                                    env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(80):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{cls.port}/api/deposit/depositions", timeout=1)
                break
            except Exception:
                time.sleep(0.1)
        cls.env = dict(os.environ, ZENODO_API_BASE=f"http://127.0.0.1:{cls.port}/api",
                       ZENODO_TOKEN="test-token-not-a-real-credential", PYTHONPATH=ROOT)
        cls.env.pop("ZENODO_SANDBOX", None)
        with open(os.path.join(cls.work, "art.txt"), "w") as fh:
            fh.write("artifact one\n")
        cls.first = cls.misty("publish", "-m", cls.meta(), "-f", os.path.join(cls.work, "art.txt"),
                              "--no-package", "--output", os.path.join(cls.work, "p.json"))
        assert cls.first.returncode == 0, cls.first.stderr
        cls.v1 = json.load(open(os.path.join(cls.work, "p.json")))

    @classmethod
    def tearDownClass(cls):
        cls.mock.terminate(); cls.mock.wait()
        subprocess.run(["rm", "-rf", cls.work])

    @classmethod
    def meta(cls, **over):
        m = dict(META, **over)
        p = os.path.join(cls.work, f"meta-{abs(hash(json.dumps(m, sort_keys=True)))}.json")
        json.dump(m, open(p, "w"))
        return p

    @classmethod
    def misty(cls, *args):
        r = subprocess.run([sys.executable, "-m", "misty.cli", *args], cwd=cls.work, env=cls.env,
                           capture_output=True, text=True)
        return r

    def deps(self):
        return json.load(urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/api/deposit/depositions?all_versions=true&size=100"))

    def concept(self):
        return self.v1["concept_doi"]

    def newversion(self, version, *extra, files=("art2.txt",)):
        paths = []
        for f in files:
            p = os.path.join(self.work, f)
            open(p, "w").write(f"{f} for {version}\n")
            paths.append(p)
        out = os.path.join(self.work, f"nv-{version}.json")
        r = self.misty("newversion", "-m", self.meta(version=version), "-f", *paths, "--no-guard",
                       "--output", out, *extra)
        return r, (json.load(open(out)) if r.returncode == 0 and os.path.exists(out) else None)

    def test_1_same_version_is_refused(self):
        r, _ = self.newversion("1.0.0", "-c", self.concept())
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("already the latest version", r.stderr)

    def test_2_new_version_beneath_the_concept_with_files_replaced(self):
        r, res = self.newversion("1.1.0", "-c", self.concept())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(res["concept_doi"], self.concept())
        self.assertNotEqual(res["doi"], self.v1["doi"])
        self.assertEqual(res["previous_doi"], self.v1["doi"])
        new = [d for d in self.deps() if d["doi"] == res["doi"]][0]
        self.assertEqual([f["key"] for f in new["files"]], ["art2.txt"])
        self.assertEqual(new["metadata"]["version"], "1.1.0")

    def test_3_an_old_record_is_refused_and_the_latest_named(self):
        r, _ = self.newversion("1.2.0", "-r", str(self.v1["deposition_id"]))
        self.assertEqual(r.returncode, 2, r.stderr)
        self.assertIn("is not the latest published version", r.stderr)

    def test_4_an_open_draft_is_reopened_not_stacked(self):
        r, _ = self.newversion("1.2.0", "-c", self.concept(), "--no-publish")
        self.assertEqual(r.returncode, 0, r.stderr)
        r, res = self.newversion("1.2.0", "-c", self.concept())
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("already exists under this concept", r.stderr)
        mine = [d for d in self.deps() if str(d["conceptrecid"]) == self.concept().split(".")[-1]]
        self.assertEqual(sum(1 for d in mine if d["state"] != "done"), 0)
        self.assertEqual(len(mine), 3)

    def test_5_lineage_relations_are_left_to_zenodo(self):
        m = self.meta(version="1.3.0", related_identifiers=[
            {"identifier": self.concept(), "relation": "isVersionOf", "scheme": "doi"}])
        p = os.path.join(self.work, "art5.txt"); open(p, "w").write("five\n")
        r = self.misty("newversion", "-c", self.concept(), "-m", m, "-f", p, "--no-guard")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("dropped related identifier", r.stderr)

    def test_6_update_corrects_metadata_and_keeps_the_doi(self):
        latest = self.misty("latest", "-c", self.concept())
        self.assertEqual(latest.returncode, 0, latest.stderr)
        lid = int(latest.stdout.strip().splitlines()[-1])
        rec = [d for d in self.deps() if d["id"] == lid][0]
        ver = rec["metadata"]["version"]
        r = self.misty("update", "-c", self.concept(), "-m",
                       self.meta(version=ver, description="Corrected. © 1993–2026 Abhishek Choudhary. All rights reserved."))
        self.assertEqual(r.returncode, 0, r.stderr)
        after = [d for d in self.deps() if d["id"] == lid][0]
        self.assertEqual(after["doi"], rec["doi"])
        self.assertTrue(after["metadata"]["description"].startswith("Corrected."))
        r = self.misty("update", "-c", self.concept(), "-m", self.meta(version="9.9.9"))
        self.assertEqual(r.returncode, 2)
        self.assertIn("never an edit of the old one", r.stderr)

    def test_8_a_version_doi_where_the_concept_was_meant_is_resolved(self):
        r, res = self.newversion("3.0.0", "-c", self.v1["doi"])
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("is a version; its concept is", r.stderr)
        self.assertEqual(res["concept_doi"], self.concept())

    def test_7_dry_run_looks_up_and_creates_nothing(self):
        before = len(self.deps())
        r, res = self.newversion("2.0.0", "-c", self.concept(), "--dry-run")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.deps()), before)
        self.assertTrue(res["previous_doi"])


class VersionsWhenTheDraftIsTheAnswer(Versions):
    """Some deployments answer newversion with the draft itself, not the parent."""
    rdm = "1"


if __name__ == "__main__":
    unittest.main()
