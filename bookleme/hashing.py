"""Deterministic hashing helpers used for cache keys and stage idempotency."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path | str) -> str:
    p = Path(path)
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_json(obj: object) -> str:
    return sha256_text(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def stage_input_hash(parts: list[object]) -> str:
    """Hash a list of strings / Paths / JSON-serialisable objects.

    Path objects are hashed by *content* so that editing a config or prompt
    automatically invalidates every downstream stage.
    """
    h = hashlib.sha256()
    for part in parts:
        if isinstance(part, Path):
            part = str(part)
        if isinstance(part, str) and len(part) < 4096 and Path(part).is_file():
            # A missing upstream output changes the hash (literal string instead
            # of content digest), which forces this stage to recompute.
            h.update(b"FILE:")
            h.update(part.encode("utf-8"))
            h.update(sha256_file(part).encode("ascii"))
        elif isinstance(part, str):
            h.update(b"STR:")
            h.update(part.encode("utf-8"))
        else:
            h.update(b"JSON:")
            h.update(json.dumps(part, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return h.hexdigest()
