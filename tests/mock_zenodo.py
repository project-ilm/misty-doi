#!/usr/bin/env python3
"""A local stand-in for the Zenodo deposit API.

Live Zenodo is deliberately NOT contacted by this test. Minting is irreversible
and a test that mints is a test you cannot run twice. This implements the exact
subset misty uses — create, bucket upload, metadata, publish, newversion, file
delete, discard, list — with Zenodo's concept/version DOI semantics, so the
newversion flow can be proven for real against something that behaves like the
service.

Run: python3 mock_zenodo.py <port>
"""
import json, re, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer

STATE = {"next_id": 1000, "dep": {}, "concept": {}, "next_concept": 500}
LOCK = threading.Lock()
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8799
BASE = lambda: f"http://127.0.0.1:{PORT}"


def new_dep(concept_id=None, inherit_from=None):
    with LOCK:
        STATE["next_id"] += 1
        did = STATE["next_id"]
        if concept_id is None:
            STATE["next_concept"] += 1
            concept_id = STATE["next_concept"]
        dep = {
            "id": did,
            "conceptrecid": concept_id,
            "conceptdoi": f"10.5281/zenodo.{concept_id}",
            "doi": None,
            "state": "unsubmitted",
            "submitted": False,
            "metadata": {},
            "files": [],
            "links": {
                "bucket": f"{BASE()}/api/files/bucket-{did}",
                "self": f"{BASE()}/api/deposit/depositions/{did}",
                "html": f"{BASE()}/record/{did}",
            },
        }
        if inherit_from:
            src = STATE["dep"][inherit_from]
            dep["metadata"] = json.loads(json.dumps(src["metadata"]))
            # Zenodo hands the new draft the previous version's files
            dep["files"] = json.loads(json.dumps(src["files"]))
        STATE["dep"][did] = dep
        STATE["concept"].setdefault(concept_id, []).append(did)
        return dep


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _send(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(n) if n else b""
        try:
            return json.loads(raw or b"{}"), raw
        except Exception:
            return {}, raw

    def do_POST(self):
        p = self.path.split("?")[0]
        if p == "/api/deposit/depositions":
            return self._send(201, new_dep())
        m = re.match(r"/api/deposit/depositions/(\d+)/actions/(\w+)$", p)
        if m:
            did, action = int(m.group(1)), m.group(2)
            dep = STATE["dep"].get(did)
            if not dep:
                return self._send(404, {"message": "no such deposition"})
            if action == "publish":
                if not dep["files"]:
                    return self._send(400, {"message": "a record must have files"})
                dep["state"], dep["submitted"] = "done", True
                dep["doi"] = f"10.5281/zenodo.{dep['id']}"
                dep["metadata"]["doi"] = dep["doi"]
                return self._send(202, dep)
            if action == "newversion":
                if dep["state"] != "done":
                    return self._send(403, {"message": "can only version a published record"})
                draft = new_dep(concept_id=dep["conceptrecid"], inherit_from=did)
                parent = json.loads(json.dumps(dep))
                parent["links"]["latest_draft"] = f"{BASE()}/api/deposit/depositions/{draft['id']}"
                return self._send(201, parent)
            if action == "discard":
                if dep["state"] == "done":
                    return self._send(403, {"message": "cannot discard a published record"})
                STATE["dep"].pop(did, None)
                return self._send(201, {"discarded": did})
        self._send(404, {"message": "not found"})

    def do_PUT(self):
        p = self.path.split("?")[0]
        m = re.match(r"/api/files/bucket-(\d+)/(.+)$", p)
        if m:
            did, name = int(m.group(1)), m.group(2)
            _, raw = self._body()
            dep = STATE["dep"][did]
            f = {"id": f"f{len(dep['files'])+1}-{did}", "key": name,
                 "filename": name, "size": len(raw)}
            dep["files"].append(f)
            return self._send(201, f)
        m = re.match(r"/api/deposit/depositions/(\d+)$", p)
        if m:
            did = int(m.group(1))
            body, _ = self._body()
            dep = STATE["dep"][did]
            dep["metadata"].update(body.get("metadata", {}))
            return self._send(200, dep)
        self._send(404, {"message": "not found"})

    def do_DELETE(self):
        m = re.match(r"/api/deposit/depositions/(\d+)/files/([\w.-]+)$", self.path.split("?")[0])
        if m:
            did, fid = int(m.group(1)), m.group(2)
            dep = STATE["dep"][did]
            before = len(dep["files"])
            dep["files"] = [f for f in dep["files"] if f["id"] != fid]
            return self._send(204 if len(dep["files"]) < before else 404, {})
        self._send(404, {"message": "not found"})

    def do_GET(self):
        p, _, q = self.path.partition("?")
        if p == "/api/deposit/depositions":
            params = dict(kv.split("=", 1) for kv in q.split("&") if "=" in kv)
            page = int(params.get("page", 1))
            size = int(params.get("size", 100))
            deps = list(STATE["dep"].values())
            if params.get("all_versions", "").lower() not in ("true", "1"):
                latest = {}
                for d in deps:
                    latest[d["conceptrecid"]] = d
                deps = list(latest.values())
            start = (page - 1) * size
            return self._send(200, deps[start:start + size])
        m = re.match(r"/api/deposit/depositions/(\d+)$", p)
        if m:
            dep = STATE["dep"].get(int(m.group(1)))
            return self._send(200, dep) if dep else self._send(404, {"message": "gone"})
        self._send(404, {"message": "not found"})


if __name__ == "__main__":
    print(f"mock zenodo on {BASE()}", flush=True)
    HTTPServer(("127.0.0.1", PORT), H).serve_forever()
