"""Minimal RTF text extraction (stdlib only). Complex destinations are dropped."""

from __future__ import annotations

import re
from pathlib import Path


def extract(path: Path) -> dict:
    raw = path.read_bytes().decode("latin-1", errors="replace")
    # Drop destination groups whose content is not document text.
    raw = re.sub(r"\{\\\*(?:fonttbl|colortbl|stylesheet|info|pict|object|generator)[^}]*\}", "", raw, flags=re.I)
    raw = raw.replace("\\par", "\n").replace("\\line", "\n").replace("\\tab", "\t")
    raw = re.sub(r"\\'([0-9a-fA-F]{2})", lambda m: bytes([int(m.group(1), 16)]).decode("latin-1"), raw)
    raw = re.sub(r"\\[a-zA-Z]+-?\d*\s?", "", raw)
    raw = raw.replace("{", "").replace("}", "")
    return {"raw_text": raw, "toc": [], "status": "ok",
            "figure_text_lost": True, "ocr_used": False,
            "source_id": path.name, "path": str(path)}
