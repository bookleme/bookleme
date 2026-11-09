"""Atomic capability extraction.

This batch ships two deterministic extractors:
  * deterministic-markup: reads explicit [CAP] blocks (used by synthetic eval books,
    giving exact golden spans);
  * heuristic: falls back to heading-level cards when no markup exists.

The LLM extractor is an interface placeholder for a later batch. Nothing here
claims to have reproduced an author's reasoning with model judgement.
"""

from __future__ import annotations

import re

_CAP_START = re.compile(r"^\s*\[CAP\]\s*(.+?)\s*$")
_FIELD = re.compile(r"^\s*(R|I|A1|A2|A3|B)\s*[:：]\s*(.*)$")
_FIELD_MAP = {
    "R": "R_quote", "I": "I_rephrase", "A1": "A1_author_case",
    "A2": "A2_user_trigger", "A3": "A3_steps", "B": "B_not_applicable",
}
_SIX = list(_FIELD_MAP.values())


def _parse_markup(text: str) -> list[dict]:
    blocks: list[dict] = []
    current: dict | None = None
    for line in text.splitlines():
        m = _CAP_START.match(line)
        if m:
            if current:
                blocks.append(current)
            current = {"title": m.group(1), **{k: "" for k in _SIX}, "A3_steps": []}
            continue
        if current is None:
            continue
        f = _FIELD.match(line)
        if not f:
            continue
        key, value = _FIELD_MAP[f.group(1)], f.group(2).strip()
        if key == "A3_steps":
            current[key] = [p.strip() for p in re.split(r"[|｜]", value) if p.strip()]
        else:
            current[key] = value
    if current:
        blocks.append(current)
    return [b for b in blocks if b["R_quote"]]


def _heading_content_start(body: str, heading: str) -> int:
    """返回标题行之后的正文起点。

    合并段（目录行并入后继段）前面带有目录/前置内容，标题文本可能出现多次；
    取最后一次出现在行首（或 `## ` 等标题标记之后）的标题，确保引文来自真实正文。
    """
    h = (heading or "").strip()
    if not h:
        return 0
    best = 0
    for m in re.finditer(re.escape(h), body):
        line_start = body.rfind("\n", 0, m.start()) + 1
        if re.fullmatch(r"#{0,6}\s*", body[line_start:m.start()]):
            best = m.end()
    return best


def _first_sentence_quote(content: str, quote_chars: int) -> str:
    """取正文首句作为逐字引文；超预算时在从句边界截断。

    只做切片与两端去空白——结果恒为原文子串，`full_text.find(quote)` 必命中。
    绝不折叠内部空白（那会破坏逐字性，正是真实书稿踩过的坑）。
    边界搜索窗口放宽到 quote_chars+8：优先在从句边界（≥8 字处）收口，
    避免「有这样一」式硬切半句；结果仍 ≤ 窗口上限。
    """
    content = content.strip()
    if not content:
        return ""
    m = re.search(r"[。！？]", content)
    sentence = content[:m.end()] if m else content
    if len(sentence) <= quote_chars:
        return sentence.rstrip()
    window = sentence[:quote_chars + 8]
    cuts = [mm.end() for mm in re.finditer(r"[，、；：]", window) if mm.end() >= 8]
    quote = sentence[:cuts[-1]] if cuts else sentence[:quote_chars]
    return quote.rstrip().rstrip("，、；：").rstrip()


def _heuristic(text: str, segments: list[dict], max_caps: int = 16, quote_chars: int = 16) -> list[dict]:
    """Low-confidence fallback: one card per heading, quote taken verbatim from source.

    引文预算：S7 版权门要求引文总量 ≤ 产物字符的 3%。每卡产物约 400 字符、
    固定部分约 2900 字符，16 卡时预算约 260 字符 → 每卡引文取 16 字以内
    （与合成样例 [CAP] 引文同量级）；完整溯源由 span.char_start 承担。
    """
    blocks = []
    for seg in segments:
        if len(blocks) >= max_caps:
            break
        start, end = seg["char_range"]
        body = text[start:end]
        heading = seg["heading"].strip()
        content = body[_heading_content_start(body, heading):]
        first = _first_sentence_quote(content, min(quote_chars, 150))
        if not first:
            continue
        blocks.append({
            "title": heading,
            "R_quote": first,
            "I_rephrase": f"按「{heading}」所界定的条件判断当前情境，再决定是否套用该方法。",
            "A1_author_case": "该章节给出的原始说明（见出处）。",
            "A2_user_trigger": f"当用户的问题涉及「{heading}」时触发。",
            "A3_steps": ["确认适用条件", "按框架逐项检查", "给出带出处的结论或说明边界"],
            "B_not_applicable": "不适用：书中未覆盖的问题，应明确回答「书里没讲」。",
        })
    return blocks


def _segment_for(pos: int, segments: list[dict]) -> str:
    for seg in segments:
        start, end = seg["char_range"]
        if start <= pos < end:
            return seg["segment_id"]
    return segments[0]["segment_id"] if segments else "seg-000"


def extract_capabilities(full_text: str, segments: list[dict], config: dict) -> dict:
    blocks = _parse_markup(full_text)
    extractor = "deterministic-markup"
    if not blocks:
        blocks = _heuristic(full_text, segments,
                            quote_chars=min(16, config["max_quote_chars"]))
        extractor = "heuristic"

    caps = []
    for i, block in enumerate(blocks, 1):
        quote = block["R_quote"]
        pos = full_text.find(quote)
        if pos < 0:
            from ..extract.base import normalize
            q_norm, _ = normalize(quote)
            pos = full_text.find(q_norm)
            quote = q_norm
            block["R_quote"] = quote
        span = {
            "segment_id": _segment_for(pos, segments) if pos >= 0 else "seg-000",
            "char_start": pos, "char_end": pos + len(quote) if pos >= 0 else -1,
            "section": _segment_for(pos, segments) if pos >= 0 else "seg-000",
            "page": 0, "chapter": "",
        }
        caps.append({
            "capability_id": f"CAP-{i:04d}",
            "title": block["title"],
            "genre_tags": [],
            "engine_targets": ["knowledge_pack", "behavior_skill"],
            "source_id": "SRC-001",
            "span": span,
            "ria": {k: block[k] for k in _SIX},
            "claims": [f"CLM-{i:04d}"],
            "checks": {"v1": [], "v2_predictive_q": "", "v2_pass": None,
                       "v3_uniqueness": None, "v3_pass": None},
            "confidence": {"tier": "S" if extractor == "deterministic-markup" else "C",
                           "score": 0.9 if extractor == "deterministic-markup" else 0.4},
            "status": "draft",
        })

    return {
        "schema_version": "1.0",
        "book_sha256": "",  # filled by pipeline
        "extractor": extractor,
        "capabilities": caps,
    }
