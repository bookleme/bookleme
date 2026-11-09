"""MOBI/AZW3 require Calibre's ebook-convert; deferred rather than aborting."""

from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


def extract(path: Path) -> dict:
    exe = shutil.which("ebook-convert")
    if not exe:
        return {"raw_text": "", "toc": [], "status": "deferred",
                "figure_text_lost": True, "ocr_used": False,
                "reason": "Calibre ebook-convert not found; convert to EPUB/TXT and retry",
                "source_id": path.name, "path": str(path)}
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "converted.txt"
        proc = subprocess.run([exe, str(path), str(out)], capture_output=True, text=True, timeout=180)
        if proc.returncode != 0 or not out.exists():
            return {"raw_text": "", "toc": [], "status": "skipped",
                    "figure_text_lost": True, "ocr_used": False,
                    "reason": proc.stderr[-300:], "source_id": path.name, "path": str(path)}
        return {"raw_text": out.read_text(encoding="utf-8", errors="replace"),
                "toc": [], "status": "ok", "figure_text_lost": True,
                "ocr_used": False, "source_id": path.name, "path": str(path)}
