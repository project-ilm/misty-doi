"""Smoke tests for misty-doi: import, version, init, validate, dry-run."""
import json, subprocess, sys, shutil
import misty

# Fall back to the module entry point so the suite runs from a source checkout
# where the console script has not been installed.
_exe = shutil.which("misty")
MISTY = [_exe] if _exe else [sys.executable, "-m", "misty.cli"]

def test_version_matches_package():
    # __version__ must match pyproject (regression for the 1.0.0/1.0.1 drift).
    # Read it rather than hard-coding, so a release cannot break its own guard.
    import pathlib, re as _re
    pp = pathlib.Path(__file__).resolve().parents[1] / "pyproject.toml"
    want = _re.search(r'^version = "([^"]+)"', pp.read_text(), _re.M).group(1)
    assert misty.__version__ == want

def test_init_writes_valid_json(tmp_path):
    out = tmp_path / "metadata.json"
    subprocess.run([*MISTY, "init", "-o", str(out)], check=True)
    data = json.loads(out.read_text())
    assert "title" in data and "upload_type" in data

def test_validate_accepts_example(tmp_path):
    out = tmp_path / "metadata.json"
    subprocess.run([*MISTY, "init", "-o", str(out)], check=True)
    # fill the minimum a validate needs
    d = json.loads(out.read_text())
    d.update({"title": "Smoke Test", "description": "Smoke test artifact.", "creators": [{"name": "Test, A."}]})
    out.write_text(json.dumps(d))
    r = subprocess.run([*MISTY, "validate", "-m", str(out)])
    assert r.returncode == 0

def test_dry_run_state(tmp_path):
    out = tmp_path / "metadata.json"
    subprocess.run([*MISTY, "init", "-o", str(out)], check=True)
    d = json.loads(out.read_text())
    d.update({"title": "Smoke Test", "description": "Smoke test artifact.", "creators": [{"name": "Test, A."}]})
    out.write_text(json.dumps(d))
    res = tmp_path / "result.json"
    subprocess.run([*MISTY, "publish", "-m", str(out), "-f", str(out),
                    "--dry-run", "--package-dir", str(tmp_path/"pkg"),
                    "--output", str(res)], check=True)
    assert json.loads(res.read_text()).get("state") == "dry-run"
