"""输入整形：把「用户手上有什么」变成「流水线要什么」。

用户不该先学我们的命令行约定。他能给的通常是：

- 一个网址（论文 / 博客 / 文档页）—— 以前得先 `bookleme fetch` 再 `bookleme run`，
  两步、两次记路径；现在一条 `--input <url>` 就行；
- 一个目录（一堆章节 md、一份拆开的书）—— 不该要求他逐个列出；
- 一个文件名不像书名的本地文件（`1714.某书.pdf`）—— 书名不该自动变成 `1714.某书`。

这里只做确定性的整理，不猜内容：书名依次取自文档自带标题 → 首个一级标题 →
清洗过的文件名，并在日志里说明取自哪里，让人知道能不能改。
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

SUPPORTED = {".md", ".markdown", ".txt", ".pdf", ".docx", ".epub", ".html", ".htm",
             ".rtf", ".mobi"}

_LEADING_NOISE = re.compile(r"^[\d\s._\-（）()\[\]【】]+")
_HEADING = re.compile(r"^#\s+(.+?)\s*$", re.M)
_HTML_TITLE = re.compile(r"<title[^>]*>(.+?)</title>", re.I | re.S)


def is_url(raw: str) -> bool:
    return raw.lower().startswith(("http://", "https://"))


def expand_paths(raw_inputs: list[str]) -> tuple[list[str], list[str]]:
    """把目录摊平成文件列表；返回 (本地文件, 网址)。顺序保持用户给的顺序。"""
    files: list[str] = []
    urls: list[str] = []
    for raw in raw_inputs:
        if is_url(raw):
            urls.append(raw)
            continue
        p = Path(raw).expanduser()
        if p.is_dir():
            picked = sorted(q for q in p.rglob("*")
                            if q.is_file() and q.suffix.lower() in SUPPORTED
                            and not any(part.startswith(".") for part in q.relative_to(p).parts))
            files.extend(str(q) for q in picked)
        else:
            files.append(str(p))
    return files, urls


def _clean_stem(stem: str) -> str:
    """`1714.某书_v2` → `某书`；只去编号与分隔噪声，不改字。"""
    s = stem.strip()
    s = re.sub(r"[_\s]+", " ", s)
    s = _LEADING_NOISE.sub("", s).strip()
    s = re.sub(r"\s*[-–—]\s*(最终版|终稿|初稿|v\d+|final|draft)$", "", s, flags=re.I)
    return s.strip() or stem.strip()


def infer_title(paths: list[str], fetched: list[dict] | None = None) -> tuple[str, str]:
    """返回 (书名, 取自哪里)。取自哪里要能对用户说清楚，方便他决定是否覆盖。"""
    for raw in paths:
        p = Path(raw)
        suffix = p.suffix.lower()
        try:
            if suffix in {".md", ".markdown", ".txt"}:
                head = p.read_text(encoding="utf-8", errors="replace")[:4000]
                m = _HEADING.search(head)
                if m:
                    return m.group(1).strip()[:80], f"{p.name} 的首个一级标题"
            elif suffix in {".html", ".htm"}:
                head = p.read_text(encoding="utf-8", errors="replace")[:8000]
                m = _HTML_TITLE.search(head)
                if m:
                    return re.sub(r"\s+", " ", m.group(1)).strip()[:80], f"{p.name} 的 <title>"
            elif suffix == ".pdf":
                title = _pdf_title(p)
                if title:
                    return title[:80], f"{p.name} 的文档元数据"
        except OSError:
            continue

    for record in fetched or []:
        name = record.get("title") or Path(str(record.get("file") or "")).stem
        if name:
            return _clean_stem(name), "抓取页面的文件名"

    if paths:
        p = Path(paths[0])
        return _clean_stem(p.stem), f"{p.name} 的文件名（可用 --title 覆盖）"
    return "未命名书稿", "没有可用输入（请给 --title）"


def short_title(title: str, limit: int = 12) -> str:
    """用于产物显示名：截断时不要把括号截成半边（会变成 `书（合成评测·教练`）。

    截断按「视觉宽度」而非字符数：中日韩字符算 2 宽，拉丁字符算 1 宽。
    为什么要按宽度：原来的纯字符数上限（12）对中文合适（12 个汉字约等于
    12 个西文字符的视觉长度），但对英文标题会砍得太狠 —— 'RL Infrastructure
    at Microsoft AI' 被截成 'RL Infrastru'，既丢信息又难看（实测产物目录名
    就是 'RL Infrastru·框架速查'）。

    拉丁文额外按词边界收口，避免切出 'RL Infrastruc' 这种半个词。
    """
    t = (title or "").strip()
    if not t:
        return t
    budget = limit * 2
    if _display_width(t) <= budget:
        return t
    cut = t[:limit]
    for left, right in (("（", "）"), ("(", ")"), ("【", "】"), ("[", "]")):
        if cut.count(left) > cut.count(right):
            cut = cut[:cut.rindex(left)]
    cut = cut.rstrip("·-—、,，.。：: （(")
    # 拉丁文按词边界收口：不在单词中间断开。
    # 不能简单退到最后一个空格（'RL Infrastructure at Microsoft AI' 会缩成
    # 'RL'）；正确做法是从完整标题重新按词组装，保留宽度在预算内的最长前缀。
    if re.search(r"[A-Za-z0-9]$", cut):
        acc = ""
        for word in t.split(" "):
            cand = (acc + " " + word) if acc else word
            if _display_width(cand) > budget:
                break
            acc = cand
        if acc.strip():
            cut = acc.rstrip("·-—、,，.。：: （(")
    return cut.rstrip() or t[:limit]


def _display_width(s: str) -> int:
    """视觉宽度：CJK 全角字符算 2，其余算 1。"""
    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return w


def _pdf_title(path: Path) -> str:
    """PDF 自带的 /Title 常常是排版软件写的乱码，只在像书名时才采用。"""
    try:
        from pypdf import PdfReader  # 可选依赖：没有就跳过，不影响主流程
    except Exception:
        return ""
    try:
        meta = (PdfReader(str(path)).metadata or {})
    except Exception:
        return ""
    raw = str(meta.get("/Title") or "").strip()
    if not raw or len(raw) < 2:
        return ""
    # 明显是生成器留下的痕迹就当作没有
    if re.search(r"\.(docx?|indd|qxd|tex|pdf)$", raw, re.I) or raw.lower() in {"untitled", "无标题"}:
        return ""
    return raw
