"""Streaming checksums (constant memory, large-artifact safe)."""

from __future__ import annotations

import hashlib
import os
from typing import Dict


def sha256_file(path: str, chunk: int = 1 << 20) -> str:
    """Return the hex SHA-256 of a file, read in 1 MiB chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def file_record(path: str) -> Dict[str, object]:
    """A reproducibility record for one file: name, size, sha256."""
    return {
        "name": os.path.basename(path),
        "size": os.path.getsize(path),
        "sha256": sha256_file(path),
    }
