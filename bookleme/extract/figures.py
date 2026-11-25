"""Figure & table extraction: verbatim captions + raster images where available.

Design constraints (BookLeme 2.0):
- Captions are verbatim slices located in the normalized corpus, so they flow
  through the same char-level traceability as R_quote; a caption that cannot be
  located keeps its text but gets position=null (shipped, honestly unanchored).
- Raster images come from pypdf page.images. Vector-only figures (most LaTeX
  papers) degrade to caption-only entries — never fabricated, never faked.
- Pairing rule is document order within a page: the N-th caption pairs with the
  N-th raster image on that page; leftovers become caption-only / image-only.
"""

from __future__ import annotations

import re
from pathlib import Path

from .base import normalize

# Caption lines: 图N / 表N / Figure N / Fig. N / Table N (line-ish, capped length)
_CAPTION_RE = re.compile(
    r"(?:^|\n)[ \t]*((?:图|表)\s*\d{1,3}[\.．、\-—:：]?\s*\S[^\n]{0,120}"
    r"|(?:Figure|Fig\.?|Table|TABLE)\s+\d{1,3}[\.．:：]?\s*\S[^\n]{0,120})"
)

_MAGIC = [
    (b"\x89PNG\r\n\x1a\n", "png"),
    (b"\xff\xd8\xff", "jpg"),
    (b"GIF87a", "gif"),
    (b"GIF89a", "gif"),
    (b"RIFF", "webp"),
    (b"BM", "bmp"),
    (b"II*\x00", "tiff"),
    (b"MM\x00*", "tiff"),
]


def image_ext(data: bytes) -> str:
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    return ""


def find_figure_captions(text: str) -> list[dict]:
    """Locate caption lines in normalized text. Pure function, fully testable.

    Returns [{"caption", "start", "end", "kind"}] with kind in figure|table.
    """
    out: list[dict] = []
    for m in _CAPTION_RE.finditer(text):
        cap = m.group(1).strip()
        kind = "table" if re.match(r"^(表|Table|TABLE)", cap) else "figure"
        start = m.start(1)
        out.append({"caption": cap, "start": start, "end": start + len(cap), "kind": kind})
    return out


def extract_pdf_figures(path: Path) -> list[dict]:
    """Extract figures from a PDF: per-page captions paired with raster images.

    Returns entries [{"page", "kind", "caption", "image": bytes|None, "ext": str}].
    Empty list when pypdf is unavailable or the file is unreadable — callers
    treat that as honest degradation, never as an error to hide.
    """
    try:
        from pypdf import PdfReader
    except ImportError:
        return []
    try:
        reader = PdfReader(str(path))
    except Exception:
        return []
    entries: list[dict] = []
    for pno, page in enumerate(reader.pages, 1):
        try:
            page_text = page.extract_text() or ""
        except Exception:
            page_text = ""
        norm, _ = normalize(page_text)
        caps = find_figure_captions(norm)
        imgs: list[bytes] = []
        try:
            for img in page.images:
                data = getattr(img, "data", b"") or b""
                if data and image_ext(data):
                    imgs.append(data)
        except Exception:
            imgs = []
        for i, cap in enumerate(caps):
            has_img = i < len(imgs)
            entries.append({
                "page": pno, "kind": cap["kind"], "caption": cap["caption"],
                "image": imgs[i] if has_img else None,
                "ext": image_ext(imgs[i]) if has_img else "",
            })
        for i in range(len(caps), len(imgs)):
            entries.append({"page": pno, "kind": "figure", "caption": "",
                            "image": imgs[i], "ext": image_ext(imgs[i])})
    return entries


def html_figure_entries(public_record: dict, base_dir: Path) -> list[dict]:
    """Build figure entries from a fetch record's downloaded images.

    Returns [{"page": None, "kind", "caption", "image": bytes|None, "ext"}].
    """
    out: list[dict] = []
    for img in public_record.get("images", []):
        rel = img.get("file", "")
        p = base_dir / rel if rel else None
        data = p.read_bytes() if p and p.is_file() else None
        caption = (img.get("caption") or img.get("alt") or "").strip()
        out.append({"page": None, "kind": "figure", "caption": caption,
                    "image": data, "ext": p.suffix.lstrip(".") if p else ""})
    return out


def locate_captions(entries: list[dict], full_text: str) -> None:
    """Anchor each entry's caption in the global normalized corpus (in place).

    Sets char_start/char_end to the caption's position in full_text, or null
    when the caption cannot be located (e.g. split across a source boundary).
    """
    index: dict[str, int] = {}
    for m in find_figure_captions(full_text):
        index.setdefault(m["caption"], m["start"])
    for e in entries:
        pos = index.get(e["caption"], -1) if e["caption"] else -1
        e["char_start"] = pos if pos >= 0 else None
        e["char_end"] = (pos + len(e["caption"])) if pos >= 0 else None
