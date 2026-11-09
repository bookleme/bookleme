"""Document normalisation, source merging and extraction dispatch."""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

SUPPORTED_EXTENSIONS = {
    ".txt", ".text", ".md", ".markdown", ".html", ".htm", ".xhtml",
    ".pdf", ".epub", ".docx", ".rtf", ".mobi", ".azw3",
}

# Zero-width / invisible controls, including the Unicode tag block U+E0000..E007F.
_INVISIBLE = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u00ad\u180e\U000e0000-\U000e007f]")


def normalize(raw: str) -> tuple[str, list[int]]:
    """Return (normalised text, char_map) where char_map[i] is the ORIGINAL index.

    Deliberately does NOT apply NFKC to the whole text. Whole-text NFKC rewrites
    full-width forms, ligatures, circled digits and CJK compatibility ideographs
    -- legitimate prose that must stay byte-identical for verbatim quote checks.
    This matches the upstream evidence in _reference/book-to-skill/.../sanitize.py
    lines 168-176 (`test_normalization_is_scoped_to_kangxi_radicals`).

    We only: (a) strip invisible/control code points, and (b) fold Kangxi
    radicals U+2F00-U+2FDF and CJK compatibility ideographs U+F900-U+FAFF,
    which are exactly the cases where a PDF font subset emits a radical instead
    of the real character and every later grep would miss it.
    """
    out: list[str] = []
    mapping: list[int] = []
    for i, ch in enumerate(raw):
        if _INVISIBLE.match(ch):
            continue
        cp = ord(ch)
        if 0x2F00 <= cp <= 0x2FDF or 0xF900 <= cp <= 0xFAFF:
            piece = unicodedata.normalize("NFKC", ch)
        else:
            piece = ch
        for c in piece:
            if _INVISIBLE.match(c):
                continue
            out.append(c)
            mapping.append(i)
    return "".join(out), mapping


def _handler_for(ext: str):
    from . import text as _text
    from . import html as _html
    from . import pdf as _pdf
    from . import epub as _epub
    from . import docx as _docx
    from . import rtf as _rtf
    from . import mobi as _mobi

    table = {
        **{e: _text.extract for e in (".txt", ".text", ".md", ".markdown")},
        **{e: _html.extract for e in (".html", ".htm", ".xhtml")},
        ".pdf": _pdf.extract, ".epub": _epub.extract, ".docx": _docx.extract,
        ".rtf": _rtf.extract, ".mobi": _mobi.extract, ".azw3": _mobi.extract,
    }
    return table.get(ext)


def extract_source(source: dict) -> dict:
    """Extract one source into clean text + metadata. Never aborts the batch."""
    path = Path(source.get("path", ""))
    ext = path.suffix.lower()
    handler = _handler_for(ext)
    if handler is None:
        return {
            "raw_text": "", "toc": [], "status": "unsupported",
            "figure_text_lost": False, "ocr_used": False,
            "reason": f"unsupported extension {ext!r}",
        }
    try:
        return handler(path)
    except Exception as exc:  # one bad source is skipped, not fatal
        return {
            "raw_text": "", "toc": [], "status": "skipped",
            "figure_text_lost": False, "ocr_used": False,
            "reason": f"{type(exc).__name__}: {exc}",
        }


def merge(results: list[dict]) -> tuple[str, list[list[int]], list[dict]]:
    """Concatenate sources with explicit markers.

    char_map[i] == [source_index, original_char_index] for every normalised
    character i; marker/newline characters are [-1, -1]. This is what lets
    fidelity/quotes.py resolve a quote back to an exact place in a source file.
    """
    full_parts: list[str] = []
    char_map: list[list[int]] = []
    toc: list[dict] = []
    for idx, res in enumerate(results):
        norm_text, local_map = normalize(res.get("raw_text", ""))
        marker = (
            f"\n\nSOURCE: {res.get('source_id', 'unknown')} "
            f"(Path: {res.get('path', '')})\n{'=' * 80}\n\n"
        )
        full_parts.append(marker)
        char_map.extend([[-1, -1]] * len(marker))
        full_parts.append(norm_text)
        char_map.extend([[idx, m] for m in local_map])
        full_parts.append("\n")
        char_map.append([-1, -1])
        for entry in res.get("toc", []):
            toc.append({**entry, "source_id": res.get("source_id", "unknown")})
    return "".join(full_parts), char_map, toc
