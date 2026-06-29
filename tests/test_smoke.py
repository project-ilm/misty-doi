"""Smoke tests for misty-doi: import, version, init, validate, dry-run."""
import json, subprocess, sys, shutil
import misty

MISTY = shutil.which("misty") or "misty"

def test_version_matches_package():
    # __version__ must match the packaged version (regression for the 1.0.0/1.0.1 drift)
    assert misty.__version__ == "1.0.1"

def test_init_writes_valid_json(tmp_path):
    out = tmp_path / "metadata.json"
    subprocess.run([MISTY, "init", "-o", str(out)], check=True)
    data = json.loads(out.read_text())
    assert "title" in data and "upload_type" in data

def test_validate_accepts_example(tmp_path):
    out = tmp_path / "metadata.json"
    subprocess.run([MISTY, "init", "-o", str(out)], check=True)
    # fill the minimum a validate needs
    d = json.loads(out.read_text())
    d.update({"title": "Smoke Test", "description": "Smoke test artifact.", "creators": [{"name": "Test, A."}]})
    out.write_text(json.dumps(d))
    r = subprocess.run([MISTY, "validate", "-m", str(out)])
    assert r.returncode == 0

def test_dry_run_state(tmp_path):
    out = tmp_path / "metadata.json"
    subprocess.run([MISTY, "init", "-o", str(out)], check=True)
    d = json.loads(out.read_text())
    d.update({"title": "Smoke Test", "description": "Smoke test artifact.", "creators": [{"name": "Test, A."}]})
    out.write_text(json.dumps(d))
    res = tmp_path / "result.json"
    subprocess.run([MISTY, "publish", "-m", str(out), "-f", str(out),
                    "--dry-run", "--package-dir", str(tmp_path/"pkg"),
                    "--output", str(res)], check=True)
    assert json.loads(res.read_text()).get("state") == "dry-run"
