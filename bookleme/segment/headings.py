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
