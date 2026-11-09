"""HTML/XHTML extraction using only the standard library."""

from __future__ import annotations

from html.parser import HTMLParser
from pathlib import Path


class _TextParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.headings: list[dict] = []
        self._heading: tuple[int, list[str]] | None = None
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = (int(tag[1]), [])
        if tag in ("p", "br", "div", "li", "tr"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading:
            level, buf = self._heading
            self.headings.append({"heading": "".join(buf).strip(), "level": level})
            self._heading = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._heading:
            self._heading[1].append(data)
        self.parts.append(data)


def extract(path: Path) -> dict:
    from .text import extract as _text_extract
    raw = path.read_bytes().decode("utf-8", errors="replace")
    parser = _TextParser()
    parser.feed(raw)
    text = "".join(parser.parts)
    # Reuse encoding-tolerant reader only for the error path; HTML is decoded above.
    return {"raw_text": text, "toc": parser.headings, "status": "ok",
            "figure_text_lost": False, "ocr_used": False, "encoding": "utf-8-replace",
            "source_id": path.name, "path": str(path)}
