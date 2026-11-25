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


def _check_url(url: str) -> None:
    """入口校验：只允许 http/https，且拒绝内网/环回/元数据地址。

    为什么必须查：urllib 默认注册了 FileHandler，`fetch file:///etc/passwd` 会
    直接把本地文件读出来落进 sources/public/ —— 那不是「抓网页」，是任意文件读取器，
    而且落盘后还会被下一次 run 自动当语料吃掉。
    """
    parsed = urllib.parse.urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError(f"只支持 http/https 地址，收到 {scheme or '(空)'}：{url}")
    host = (parsed.hostname or "").lower()
    if not host:
        raise ValueError(f"地址缺少主机名：{url}")
    blocked_hosts = {"localhost", "127.0.0.1", "::1", "0.0.0.0",
                     "169.254.169.254", "metadata.google.internal"}
    if host in blocked_hosts or host.endswith(".localhost") or host.endswith(".internal"):
        raise ValueError(f"拒绝抓取内网/环回/云元数据地址：{host}")
    if re.match(r"^10\.", host) or re.match(r"^192\.168\.", host) \
            or re.match(r"^172\.(1[6-9]|2\d|3[01])\.", host) \
            or re.match(r"^169\.254\.", host):
        raise ValueError(f"拒绝抓取内网地址：{host}")


def _download(url: str, timeout: int = 30) -> tuple[bytes, str]:
    """Download a URL. urllib uses http_proxy/https_proxy env vars automatically."""
    _check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        ctype = resp.headers.get("Content-Type", "") or ""
        return resp.read(), ctype


# 这些标签的内容不是正文，一律跳过。
# template 必须跳过：微软等站点把 base64 数据块放在 <template data-widget-html> 里，
# HTMLParser 会照常把 template 的文本内容吐进 parts，导致语料 93% 是 base64 噪声
# （实测 microsoft.ai 页面：674,667 字符里 626,600 是 base64，正文只占 4%）。
# noscript/svg 同理（内嵌降级内容 / 图形节点文本）。
SKIP_TAGS = ("script", "style", "template", "noscript", "svg", "canvas", "iframe")

# 正文容器候选（按优先级）。命中后只取容器内的内容，去掉导航/页脚噪声。
_MAIN_SELECTORS = (
    "article", "main", "div[role=main]", "section[role=main]",
    "div=post-content", "div=entry-content", "div=article-body",
    "div=post-body", "div=content", "div=main-content", "div=rich-text",
)

# 明确的噪声容器：命中即整块丢弃。
_NOISE_TAGS = ("nav", "header", "footer", "aside", "form")

# 网页 UI 噪声标题：这些是分享控件 / 推荐位 / 页脚分组，不是章节标题。
# 一律小写规范化后比较（匹配时会对标题做同样的规范化）。
_UI_HEADINGS = frozenset({
    "share this article", "share", "related stories", "citation", "data & privacy",
    "sitemap", "contact microsoft", "privacy choices", "your privacy choices",
    "back to news", "article link", "copy link", "more from microsoft ai",
    "sign in", "sign up", "skip to main content", "accessibility mode",
    "resources", "get started", "learn more", "follow us", "newsletter",
})

# 网页 UI 噪声行（规范化后整行匹配才丢弃，避免误伤正文里的同形词）。
_UI_LINES = frozenset({
    "share", "×", "back to news", "article link", "copy link",
    "linkedin (opens in a new tab)", "x (opens in a new tab)",
    "facebook (opens in a new tab)", "linkedin", "x", "facebook",
    "close", "menu", "search", "sign in", "sign up",
})

# BibTeX 引用块尾巴（形如 howpublished={...} / year={2026}）
_BIBTEX_LINE = re.compile(
    r"^(howpublished|year|url|urldate|author|title|journal|booktitle|"
    r"publisher|pages|volume|number|month|note|doi|isbn)=\{.*\}$",
    re.I,
)


class PageParser(HTMLParser):
    """Page text + figure images (<figure>/<figcaption>/<img alt>).

    Figure semantics: an <img> inside <figure> inherits the <figcaption> text as
    its caption; a standalone <img> falls back to its alt attribute. The caption
    text also appears in the extracted content (figcaption text is kept), so the
    caption can later be located verbatim in the compiled corpus.

    正文提取策略（2.1.2）：优先取 <article>/<main>/[role=main] 等正文容器，
    取不到再退回整页文本；<nav>/<header>/<footer>/<aside> 整块丢弃。
    见 _extract_main_body()。
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
        # 正文容器候选区段：记录每个候选容器的（标签, 属性, 文本）
        self._candidates: list[tuple[str, dict, str]] = []
        self._cand_stack: list[list] = []  # [tag, attrs, parts]
        self._noise_depth = 0

    @property
    def text(self) -> str:
        return "".join(self.parts)

    # ---------- 正文容器 ----------
    def _maybe_push_candidate(self, tag: str, d: dict) -> None:
        """命中正文容器候选时开始收集该容器内的文本。"""
        attrs = {k.lower(): (v or "") for k, v in d.items()}
        is_main = (
            tag in ("article", "main")
            or attrs.get("role", "").lower() == "main"
            or attrs.get("itemprop", "").lower() == "articlebody"
            or any(f"{tag}={attrs.get(cls, '')}".strip("=") for cls in ())
        )
        if not is_main:
            for cls in ("post-content", "entry-content", "article-body", "post-body",
                        "content", "main-content", "rich-text", "markdown-body"):
                if cls in attrs.get("class", "").split():
                    is_main = True
                    break
        if is_main:
            self._cand_stack.append([tag, attrs, []])

    def _close_candidate(self, tag: str) -> None:
        if self._cand_stack and self._cand_stack[-1][0] == tag:
            t, attrs, parts = self._cand_stack.pop()
            self._candidates.append((t, attrs, "".join(parts)))

    def handle_starttag(self, tag, attrs):
        d = dict(attrs)
        if tag in SKIP_TAGS:
            self._skip += 1
            return
        if tag in _NOISE_TAGS:
            self._noise_depth += 1
            return
        if self._noise_depth:
            return
        self._maybe_push_candidate(tag, d)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
            self._heading = (int(tag[1]), [])
            # 标题是块级元素：前后都要断行。否则标题会与相邻正文黏成一行，
            # 既让标题标记化失配（行不再等于标题文本），也让 UI 噪声按行过滤
            # 失效（噪声与正文同行）。
            self.parts.append("\n")
        if tag in ("p", "br", "div", "li", "tr", "figure", "figcaption"):
            self.parts.append("\n")
        if tag == "figure":
            self._fig_imgs = []
            self._fig_caption = []
        if tag == "figcaption":
            self._in_figcaption = True
        if tag == "img":
            img = {"src": d.get("src", ""), "alt": d.get("alt", ""), "caption": "",
                   "anchor_text": self._anchor_text(),
                   "in_main": bool(self._cand_stack),
                   "in_figure": self._fig_imgs is not None}
            if self._fig_imgs is not None:
                self._fig_imgs.append(img)
            else:
                img["caption"] = img.get("alt", "")
                self.images.append(img)

    def _anchor_text(self, width: int = 80) -> str:
        """图片之前的正文片段（逐字）——用于在编译语料里定位这张图的位置。

        网页图片常常只有 alt（alt 文本不在正文里，无法在语料中定位），但图片前后的
        正文一定在语料里：截取图前一小段原文作为锚点，就能定位到语料位置。

        锚点必须取自**最终会进语料的正文**，而不是全页 parts：全页 parts 含
        导航/页脚噪声，而正文容器提取会剔除它们，两者对不上 → 锚点定位失败
        （实测 microsoft.ai 页面 3 张图 anchor_kind 全为 null）。
        所以这里优先从正文候选容器里取，取不到再退回全页。
        """
        # 1) 正文容器内的锚点（与最终语料同源）
        for _tag, _attrs, parts in reversed(self._cand_stack):
            text = "".join(parts)
            snippet = text[-width:].strip()
            if snippet:
                return snippet
        # 2) 退回全页
        text = "".join(self.parts)
        return text[-width:].strip()

    def handle_endtag(self, tag):
        if tag in SKIP_TAGS:
            if self._skip:
                self._skip -= 1
            return
        if tag in _NOISE_TAGS:
            if self._noise_depth:
                self._noise_depth -= 1
            return
        if self._noise_depth:
            return
        self._close_candidate(tag)
        if tag in ("h1", "h2", "h3", "h4", "h5", "h6") and self._heading:
            level, buf = self._heading
            self.headings.append({"heading": "".join(buf).strip(), "level": level})
            self._heading = None
            # 标题后断行（与开标签前的断行配对）
            self.parts.append("\n")
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
        if self._noise_depth:
            return
        if self._heading:
            self._heading[1].append(data)
        if self._in_figcaption and self._fig_caption is not None:
            self._fig_caption.append(data)
        self.parts.append(data)
        for cand in self._cand_stack:
            cand[2].append(data)

    # ---------- 标题标记化 ----------
    def _markup_headings(self, text: str, headings: list[dict]) -> str:
        """把 HTML 标题还原成 Markdown 标题标记，供分段器识别。

        为什么必须做：分段器靠 `## ` / `第N章` 等标题正则切段。网页正文没有
        Markdown 标记 → 全部退化成「窗口 N（无标题回退）」，框架名失去语义
        （实测 microsoft.ai 页面：16 个框架全是「窗口 N」）。

        做法：标题必须**整行**等于标题文本才算命中（不接受前缀匹配），
        否则正文首句恰好以标题词开头时会被整段标成标题。
        同时过滤 UI 噪声标题（Share this article / Related Stories 等）。
        """
        if not headings:
            return text
        usable = [h for h in headings
                  if len((h.get("heading") or "").strip()) >= 3
                  and re.sub(r"\s+", " ", (h.get("heading") or "").strip()).lower()
                  not in _UI_HEADINGS]
        # 长标题优先匹配，避免短标题先命中（"Elasticity" 会先撞上
        # "Fault tolerance and elasticity. Runs that span..." 这类长行）
        usable.sort(key=lambda h: len(h.get("heading") or ""), reverse=True)
        used: set[int] = set()
        out_lines: list[str] = []
        for line in text.split("\n"):
            stripped = line.strip()
            marked = False
            if stripped and not stripped.startswith("#"):
                for hi, h in enumerate(usable):
                    if hi in used:
                        continue
                    htxt = h["heading"].strip()
                    if stripped == htxt:
                        level = max(1, min(int(h.get("level") or 1), 6))
                        out_lines.append("#" * level + " " + stripped)
                        used.add(hi)
                        marked = True
                        break
            if not marked:
                out_lines.append(line)
        return "\n".join(out_lines)

    def _strip_ui_noise(self, body: str) -> str:
        """剔除社交分享控件 / BibTeX 尾巴 / 空按钮等 UI 文本行。

        这些行不是正文，却会切碎段落、污染引文（实测 microsoft.ai 页面开头
        就有 'Share this article' / 'LinkedIn (opens in a new tab)' 一串）。
        匹配用「去空白 + 小写」后的规范化比较，避免缩进/大小写差异漏判。
        """
        out_lines: list[str] = []
        for line in body.split("\n"):
            s = line.strip()
            if not s:
                out_lines.append(line)
                continue
            norm = re.sub(r"\s+", " ", s).lower()
            if norm in _UI_LINES or norm in _UI_HEADINGS:
                continue
            if _BIBTEX_LINE.match(norm):
                continue
            out_lines.append(line)
        return "\n".join(out_lines)

    def _truncate_tail(self, body: str) -> str:
        """截掉正文尾部不属于文章的部分：BibTeX 引用块、相关推荐位。

        网页正文容器常把「引用信息」和「相关阅读」一并放进同一个 <article>，
        它们不是文章内容，会污染末段引文与最后一张图（实测 microsoft.ai 页面
        尾部是 @misc{...} BibTeX 块 + Related Stories 推荐位）。
        """
        # 1) BibTeX 块：从 @misc{ / @article{ 起，到配对的 } 为止，整块丢弃
        m = re.search(r"@(?P<kind>misc|article|book|inproceedings|incollection|"
                      r"techreport|phdthesis|mastersthesis)\s*\{", body)
        if m:
            body = body[:m.start()]
        # 2) 相关推荐位：从最后一个「Related Stories / Related content」类标题起丢弃
        for kw in ("related stories", "related content", "related articles",
                   "more from", "recommended", "read next"):
            idx = body.lower().rfind(kw)
            if idx > 0:
                # 只在接近尾部时截断（避免误伤正文里提到的 "more from"）
                if idx > len(body) * 0.5:
                    body = body[:idx]
        return body.rstrip()

    def _extract_main_body(self) -> str:
        """从候选正文容器里挑出最好的正文块。

        评分：正文长度 + 段落数（段落多的更像正文，少于 3 段的容器多半是
        侧栏/推荐位）。同分时取更早出现的（更可能是主容器）。
        """
        best: str = ""
        best_score = 0.0
        for _tag, _attrs, body in self._candidates:
            body = body.strip()
            if not body:
                continue
            paras = [p for p in body.split("\n") if p.strip()]
            score = len(body) + 200 * len(paras)
            if score > best_score:
                best_score = score
                best = body
        return best

    def has_main_container(self) -> bool:
        """页面上是否找到了语义正文容器（<article>/<main>/[role=main]…）。"""
        return bool(self._candidates)

    def result_text(self) -> str:
        """最终语料：优先正文容器，全页文本兜底；并把标题标记化。"""
        body = self._extract_main_body()
        if len(body) < 400:
            # 没找到像样的正文容器 → 用整页文本（去掉被跳过的标签残留）
            body = self.text
        body = self._strip_ui_noise(body)
        body = self._truncate_tail(body)
        body = self._markup_headings(body, self.headings)
        # 压缩 3 行以上连续空行为 2 行，保留段落感
        body = re.sub(r"\n{3,}", "\n\n", body)
        return body.strip()


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
            # 只有在页面上确实找到了语义正文容器时，才用「在不在正文里」筛图。
            # 没有容器的页面（结构老旧/语义标记缺失）一律不过滤，否则会误杀
            # 正文图（回归测试 test_fetch_html_and_pdf_with_mocked_network
            # 就是这种页面：没有 <main>，图在 <figure> 里）。
            has_main = parser.has_main_container()
            for img in parser.images:
                if kept >= MAX_IMAGES or not img.get("src"):
                    continue
                # 只收正文容器内的图。站点 logo / 推荐位缩略图 / 页脚配图不是
                # 正文内容，却会被当成「图示」交付并挂到能力卡上，稀释质量
                # （实测 microsoft.ai 页面 11 张图里 8 张是站点装饰图）。
                if has_main and not img.get("in_main"):
                    continue
                # 装饰图判定：在 <figure> 内（有图注）或前面有正文锚点 → 是内容图；
                # 否则只是页面装饰（头图/尾图/社交分享图），交付它只会让
                # 「图示未锚定」变成常态噪音。
                if not img.get("in_figure") and not (img.get("anchor_text") or "").strip():
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
            "url": url, "content": parser.result_text(), "images": imgs,
            "retrieved_at": now,
            "tier": tier, "license_note": license_note, "bytes": len(data),
            "content_chars": len(parser.result_text()),
        }
    dump_json(out / f"{slug}.json", record)
    return record
