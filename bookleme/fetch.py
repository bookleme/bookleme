"""Fetch public web pages / papers into sources/public with provenance. Stdlib only.

Zero third-party dependencies: urllib for transport (honours http_proxy/https_proxy
environment variables), html.parser for text + figure extraction. Everything fetched
is copyright material — it lands in sources/public/ which is gitignored; nothing
from here is ever committed to the repository.
"""

from __future__ import annotations

import re
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path

from .config import ROOT, dump_json

USER_AGENT = "BookLeme/2.0 (+https://github.com/bookleme/bookleme)"
MAX_IMAGES = 24
MAX_IMAGE_BYTES = 2 * 1024 * 1024

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


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def image_ext(data: bytes) -> str:
    """Detect image format from magic bytes; '' when unknown (then we skip it)."""
    for magic, ext in _MAGIC:
        if data.startswith(magic):
            return ext
    return ""


def _download(url: str, timeout: int = 30) -> tuple[bytes, str]:
    """Download a URL. urllib uses http_proxy/https_proxy env vars automatically."""
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "") or ""
        return resp.read(), ctype


class PageParser(HTMLParser):
    """Page text + figure images (<figure>/<figcaption>/<img alt>).

    Figure semantics: an <img> inside <figure> inherits the <figcaption> text as
    its caption; a standalone <img> falls back to its alt attribute. The caption
    text also appears in the extracted content (figcaption text is kept), so the
    caption can later be located verbatim in the compiled corpus.
    """

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.headings: list[dict] = []
        self.images: list[dict] = []
        self._heading: tuple[int, list[str]] | None = None
        self._skip = 0
        self._fig_imgs: list[dict] | None = None
        self._fig_caption: list[str] | None = None
        self._in_figcaption = False

    @property
    def text(self) -> str:
        return "".join(self.parts)

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in ("script", "style"):
            self._skip += 1
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = (int(tag[1]), [])
        if tag in ("p", "br", "div", "li", "tr", "figure", "figcaption"):
            self.parts.append("\n")
        if tag == "figure":
            self._fig_imgs = []
            self._fig_caption = []
        if tag == "figcaption":
            self._in_figcaption = True
        if tag == "img":
            img = {"src": d.get("src", ""), "alt": d.get("alt", ""), "caption": "",
                   "anchor_text": self._anchor_text()}
            if self._fig_imgs is not None:
                self._fig_imgs.append(img)
            else:
                img["caption"] = img.get("alt", "")
                self.images.append(img)

    def _anchor_text(self, width: int = 80) -> str:
        """图片之前的正文片段（逐字）——用于在编译语料里定位这张图的位置。

        网页图片常常只有 alt（alt 文本不在正文里，无法在语料中定位），但图片前后的
        正文一定在语料里：截取图前一小段原文作为锚点，就能定位到语料位置。
        """
        text = "".join(self.parts)
        return text[-width:].strip()

    def handle_endtag(self, tag):
        if tag in ("script", "style") and self._skip:
            self._skip -= 1
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading:
            level, buf = self._heading
            self.headings.append({"heading": "".join(buf).strip(), "level": level})
            self._heading = None
        if tag == "figcaption":
            self._in_figcaption = False
        if tag == "figure" and self._fig_imgs is not None:
            caption = "".join(self._fig_caption or []).strip()
            for img in self._fig_imgs:
                img["caption"] = caption or img.get("alt", "")
            self.images.extend(self._fig_imgs)
            self._fig_imgs = None
            self._fig_caption = None

    def handle_data(self, data):
        if self._skip:
            return
        if self._heading:
            self._heading[1].append(data)
        if self._in_figcaption and self._fig_caption is not None:
            self._fig_caption.append(data)
        self.parts.append(data)


def slugify(url: str, name: str | None = None) -> str:
    if name:
        base = name
    else:
        parsed = urllib.parse.urlparse(url)
        base = (parsed.netloc + parsed.path).strip("/").replace("/", "-")
    base = re.sub(r"[^0-9A-Za-z._-]+", "-", base).strip("-")
    return base[-80:] or "page"


def fetch_url(url: str, *, out_dir: Path | None = None, name: str | None = None,
              tier: str = "B", license_note: str = "",
              save_images: bool = True) -> dict:
    """Fetch url into sources/public as a public source record.

    HTML → <slug>.json carrying extracted content + downloaded figure images.
    PDF  → <slug>.pdf plus a <slug>.json sidecar (kind=pdf, file=<slug>.pdf).

    Returns the record dict exactly as written to disk. The record is what
    pipeline S0/S1 consume as a public source.
    """
    out = Path(out_dir) if out_dir else ROOT / "sources" / "public"
    out.mkdir(parents=True, exist_ok=True)
    slug = slugify(url, name)
    data, ctype = _download(url)
    now = _now()
    is_pdf = (url.lower().endswith(".pdf") or "pdf" in ctype.lower()
              or data[:5] == b"%PDF-")
    if is_pdf:
        (out / f"{slug}.pdf").write_bytes(data)
        record = {
            "schema_version": "2.0", "kind": "pdf", "file": f"{slug}.pdf",
            "url": url, "content": "", "images": [], "retrieved_at": now,
            "tier": tier, "license_note": license_note, "bytes": len(data),
        }
    else:
        m = re.search(r"charset=([\w-]+)", ctype, re.I)
        enc = (m.group(1) if m else "utf-8")
        try:
            html = data.decode(enc, errors="replace")
        except LookupError:
            html = data.decode("utf-8", errors="replace")
        parser = PageParser()
        parser.feed(html)
        imgs: list[dict] = []
        if save_images:
            kept = 0
            for img in parser.images:
                if kept >= MAX_IMAGES or not img.get("src"):
                    continue
                src = urllib.parse.urljoin(url, img["src"])
                try:
                    blob, _ = _download(src)
                except Exception:
                    continue
                if not (128 <= len(blob) <= MAX_IMAGE_BYTES):
                    continue
                ext = image_ext(blob)
                if not ext:
                    continue
                img_dir = out / "images"
                img_dir.mkdir(parents=True, exist_ok=True)
                fname = f"{slug}-{kept + 1:03d}.{ext}"
                (img_dir / fname).write_bytes(blob)
                imgs.append({"file": f"images/{fname}", "src": src,
                             "alt": img.get("alt", ""), "caption": img.get("caption", ""),
                             "anchor_text": img.get("anchor_text", "")})
                kept += 1
        record = {
            "schema_version": "2.0", "kind": "html", "file": "",
            "url": url, "content": parser.text, "images": imgs, "retrieved_at": now,
            "tier": tier, "license_note": license_note, "bytes": len(data),
        }
    dump_json(out / f"{slug}.json", record)
    return record
