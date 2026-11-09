"""EPUB extraction with zipfile + stdlib XML/HTML (zero dependencies)."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile


def extract(path: Path) -> dict:
    from .html import _TextParser
    import xml.etree.ElementTree as ET

    parts: list[str] = []
    toc: list[dict] = []
    with ZipFile(path) as zf:
        names = [n for n in zf.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
        names.sort()
        for name in names:
            parser = _TextParser()
            parser.feed(zf.read(name).decode("utf-8", errors="replace"))
            parts.append("".join(parser.parts))
            for h in parser.headings:
                toc.append(h)
        ncx = next((n for n in zf.namelist() if n.lower().endswith("toc.ncx")), None)
        if ncx:
            try:
                root = ET.fromstring(zf.read(ncx))
                for label in root.iter():
                    if label.tag.endswith("text") and (label.text or "").strip():
                        toc.append({"heading": label.text.strip(), "level": 1})
            except ET.ParseError:
                pass
    return {"raw_text": "\n\n".join(parts), "toc": toc, "status": "ok",
            "figure_text_lost": True, "ocr_used": False,
            "source_id": path.name, "path": str(path)}
