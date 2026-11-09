"""Token-window fallback when a book has no detectable headings."""

from __future__ import annotations


def window_segments(text: str, size: int, overlap: int) -> list[dict]:
    step = max(1, size - overlap)
    out: list[dict] = []
    i = 0
    n = 0
    while i < len(text):
        end = min(len(text), i + size)
        body = text[i:end]
        out.append({
            "segment_id": f"seg-{n + 1:03d}",
            "heading": f"窗口 {n + 1}（无标题回退）",
            "level": 1,
            "char_range": [i, end],
            "token_est": len(body) // 2,
            "confidence": 0.35,
            "method": "window_fallback",
            "parent_id": "",
            "figure_text_lost": False,
        })
        n += 1
        if end >= len(text):
            break
        i += step
    return out
