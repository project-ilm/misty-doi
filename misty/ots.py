"""Thin wrapper over the OpenTimestamps client (`ots`).

We deliberately shell out to the reference `ots` binary rather than vendoring a
Bitcoin-aware library: it keeps Misty dependency-light and air-gap friendly
(stamp now, verify/ upgrade later when a network is available). If `ots` is
absent we say so clearly instead of failing opaquely.
"""

from __future__ import annotations

import shutil
import subprocess
from typing import List

from .errors import OTSError


def available() -> bool:
    return shutil.which("ots") is not None


def _run(args: List[str]) -> str:
    if not available():
        raise OTSError(
            "OpenTimestamps client not found. Install with `pip install opentimestamps-client` "
            "(provides the `ots` command)."
        )
    proc = subprocess.run(["ots", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise OTSError(f"`ots {' '.join(args)}` failed: {proc.stderr.strip() or proc.stdout.strip()}")
    return proc.stdout


def stamp(path: str) -> str:
    """Create ``path.ots``; returns the proof file path."""
    _run(["stamp", path])
    return path + ".ots"


def verify(path: str) -> str:
    """Verify ``path`` against ``path.ots`` (expects the .ots beside it)."""
    return _run(["verify", path])


def upgrade(ots_path: str) -> str:
    """Upgrade a pending proof once the Bitcoin attestation is available."""
    return _run(["upgrade", ots_path])
