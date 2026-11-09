"""PDF extraction via optional pypdf; scanned PDFs degrade instead of aborting."""

from __future__ import annotations

from pathlib import Path


def extract(path: Path) -> dict:
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"raw_text": "", "toc": [], "status": "deferred",
                "figure_text_lost": True, "ocr_used": False,
                "reason": "pypdf not installed for this interpreter; PDF deferred to a later batch",
                "source_id": path.name, "path": str(path)}

    reader = PdfReader(str(path))
    pages: list[str] = []
    for page in reader.pages:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pages.append("")
    text = "\n\n".join(pages)
    chars_per_page = sum(len(p) for p in pages) / max(1, len(pages))
    scanned = chars_per_page < 50
    outline = []
    try:
        for item in reader.outline:
            if isinstance(item, list):
                continue
            outline.append({"heading": str(getattr(item, "title", "")), "level": 1})
    except Exception:
        outline = []
    return {
        "raw_text": text, "toc": outline,
        "status": "scanned" if scanned else "ok",
        "figure_text_lost": True,  # pypdf does not extract figure/table text faithfully
        "ocr_used": False, "pages": len(pages), "chars_per_page": round(chars_per_page, 2),
        "source_id": path.name, "path": str(path),
    }
