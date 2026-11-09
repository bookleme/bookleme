"""Plain text / Markdown extraction with encoding fallback."""

from __future__ import annotations

from pathlib import Path


def extract(path: Path) -> dict:
    raw = path.read_bytes()
    last_error = ""
    for enc in ("utf-8-sig", "utf-8", "gb18030", "big5", "latin-1"):
        try:
            text = raw.decode(enc)
            return {
                "raw_text": text, "toc": _markdown_toc(text),
                "status": "ok", "figure_text_lost": False,
                "ocr_used": False, "encoding": enc, "source_id": path.name, "path": str(path),
            }
        except UnicodeDecodeError as exc:
            last_error = str(exc)
    return {"raw_text": "", "toc": [], "status": "skipped", "figure_text_lost": False,
            "ocr_used": False, "reason": last_error, "source_id": path.name, "path": str(path)}


def _markdown_toc(text: str) -> list[dict]:
    import re
    out = []
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if m:
            out.append({"heading": m.group(2).strip(), "level": len(m.group(1))})
    return out
