"""Structure-first segmentation. Chinese-friendly: does not depend on 'Chapter N'."""

from __future__ import annotations

import re

HEADING_PATTERNS = [
    (re.compile(r"^(#{1,6})\s+(.+?)\s*$"), lambda m: (len(m.group(1)), m.group(2))),
    (re.compile(r"^第[一二三四五六七八九十百零〇\d]+[章节]\s*(.*)$"), lambda m: (1, m.group(0))),
    (re.compile(r"^第[一二三四五六七八九十百零〇\d]+[部分篇]\s*(.*)$"), lambda m: (1, m.group(0))),
    (re.compile(r"^(?:Chapter|CHAPTER|Part|PART)\s+\d+[.:]?\s*(.*)$"), lambda m: (1, m.group(0))),
    (re.compile(r"^[一二三四五六七八九十]+、\s*(.+)$"), lambda m: (2, m.group(0))),
    (re.compile(r"^\d+(?:\.\d+)*\s+[^\d\s].{0,60}$"), lambda m: (2, m.group(0))),
]


def _match_heading(line: str):
    for pattern, extractor in HEADING_PATTERNS:
        m = pattern.match(line.strip())
        if m:
            return extractor(m)
    return None


def _merge_duplicate_headings(segments: list[dict]) -> list[dict]:
    """书籍目录行会被标题正则命中，与正文标题重名，制造大量短「假段」。

    确定性规则：同名标题保留正文出现——优先正文量大的出现（≥1000 字符），
    否则保留靠后的出现（目录在正文之前）；被删段的字符区间并入其后继保留段
    （末尾并入最后一段），保证全文无失覆盖、不产生空洞。
    """
    def norm(h: str) -> str:
        return re.sub(r"\s+", "", h or "")

    groups: dict[str, list[int]] = {}
    for i, seg in enumerate(segments):
        groups.setdefault(norm(seg["heading"]), []).append(i)

    keep: set[int] = set()
    for idxs in groups.values():
        if len(idxs) == 1:
            keep.add(idxs[0])
        else:
            long_ones = [i for i in idxs
                         if segments[i]["char_range"][1] - segments[i]["char_range"][0] >= 1000]
            keep.add((long_ones or idxs)[-1])

    kept_idxs = sorted(keep)
    result = [dict(segments[i], char_range=list(segments[i]["char_range"])) for i in kept_idxs]
    for i in range(len(segments) - 1, -1, -1):
        if i in keep:
            continue
        a, b = segments[i]["char_range"]
        nxt = next((j for j in kept_idxs if j > i), None)
        if nxt is not None:
            k = kept_idxs.index(nxt)
            result[k]["char_range"][0] = min(result[k]["char_range"][0], a)
        else:
            result[-1]["char_range"][1] = max(result[-1]["char_range"][1], b)
    # 首个标题之前的序言（书名页/目录页）并入第一段，保证全文无失覆盖。
    if result:
        result[0]["char_range"][0] = 0
    for n, seg in enumerate(result, 1):
        s, e = seg["char_range"]
        seg["segment_id"] = f"seg-{n:03d}"
        seg["token_est"] = (e - s) // 2
    return result


def segment_text(full_text: str, toc: list[dict], config: dict) -> dict:
    headings: list[tuple[int, int, str]] = []  # (char_offset, level, heading)
    offset = 0
    for line in full_text.splitlines(keepends=True):
        stripped = line.rstrip("\r\n")
        found = _match_heading(stripped)
        if found:
            headings.append((offset, found[0], found[1]))
        offset += len(line)

    if len(headings) >= 2:
        segments = []
        for i, (start, level, heading) in enumerate(headings):
            end = headings[i + 1][0] if i + 1 < len(headings) else len(full_text)
            body = full_text[start:end]
            segments.append({
                "segment_id": f"seg-{i + 1:03d}",
                "heading": heading.strip(),
                "level": level,
                "char_range": [start, end],
                "token_est": len(body) // 2,
                "confidence": 0.9,
                "method": "headings",
                "parent_id": "",
                "figure_text_lost": False,
            })
        segments = _merge_duplicate_headings(segments)
        method = "headings"
        low_confidence = False
    else:
        from .windows import window_segments
        segments = window_segments(full_text, config["segment_window_chars"], config["segment_overlap_chars"])
        method = "window_fallback"
        low_confidence = True

    return {
        "schema_version": "1.0",
        "book_sha256": "",  # filled by pipeline
        "method": method,
        "low_confidence": low_confidence,
        "toc_detected": len(toc),
        "segments": segments,
    }
