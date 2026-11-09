"""DOCX extraction: read word/document.xml paragraphs and heading styles."""

from __future__ import annotations

from pathlib import Path
from zipfile import ZipFile
import xml.etree.ElementTree as ET

_W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def extract(path: Path) -> dict:
    with ZipFile(path) as zf:
        root = ET.fromstring(zf.read("word/document.xml"))
    parts: list[str] = []
    toc: list[dict] = []
    for para in root.iter(_W + "p"):
        text = "".join((node.text or "") for node in para.iter(_W + "t"))
        if not text.strip():
            continue
        parts.append(text)
        style = para.find(f"{_W}pPr/{_W}pStyle")
        val = style.get(_W + "val", "") if style is not None else ""
        m = __import__("re").match(r"(?:Heading|标题)(\d)", val)
        if m:
            toc.append({"heading": text.strip(), "level": int(m.group(1))})
    return {"raw_text": "\n".join(parts), "toc": toc, "status": "ok",
            "figure_text_lost": True, "ocr_used": False,
            "source_id": path.name, "path": str(path)}
