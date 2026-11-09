"""Atomic capability extraction.

This batch ships three deterministic/LLM extractors:
  * deterministic-markup: reads explicit [CAP] blocks (used by synthetic eval books,
    giving exact golden spans);
  * llm: LLM-assisted cards — R_quote stays a verbatim anchor located back into the
    source (never trusted from the model output), I/A/B fields are deepened by the
    model; missing fields fall back to deterministic templates;
  * heuristic: falls back to heading-level cards when neither applies.

Every quote — regardless of extractor — must be a verbatim substring of the source,
so S5's `full_text.find(quote)` always resolves to a real char offset.
"""

from __future__ import annotations

import re
from string import Template

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


_LLM_BODY_CHARS = 3000  # 每卡送模型的正文上限（控成本；首句锚点在其内）


def _locate_quote_verbatim(full_text: str, quote: str) -> tuple[str, int]:
    """把模型给的引文定位回原文；返回 (逐字引文, 位置)。

    模型输出的引文可能带空白差异（换行↔空格）。先精确 find；不中则按
    「空白不敏感」正文定位，命中后**切原文子串**返回——引文永远逐字，
    绝不把模型的空白版本写进产物。
    """
    quote = (quote or "").strip()
    if not quote:
        return "", -1
    pos = full_text.find(quote)
    if pos >= 0:
        return quote, pos
    parts = [re.escape(p) for p in quote.split() if p]
    if not parts:
        return "", -1
    pattern = re.compile(r"\s*".join(parts))
    m = pattern.search(full_text)
    if not m:
        return "", -1
    return full_text[m.start():m.end()], m.start()


def _llm(text: str, segments: list[dict], config: dict, book_title: str,
         max_caps: int = 16) -> list[dict]:
    """LLM 抽取：I/A/B 由模型深化，R_quote 终身逐字校验（失败即丢弃该卡）。

    单卡失败不中断：跳过该段继续；全军覆没时调用方回退 heuristic。
    """
    from .. import llm as llm_mod

    prompt_full = llm_mod.load_prompt("capability_extract_v1")
    system, user_tpl = llm_mod.split_prompt(prompt_full)
    tpl = Template(user_tpl)
    blocks: list[dict] = []
    for seg in segments:
        if len(blocks) >= max_caps:
            break
        start, end = seg["char_range"]
        body = text[start:end]
        heading = seg["heading"].strip()
        content = body[_heading_content_start(body, heading):].strip()
        if not content:
            continue
        user = tpl.safe_substitute(title=book_title, heading=heading,
                                   body=content[:_LLM_BODY_CHARS])
        try:
            obj = llm_mod.chat_json(user, system=system)
        except llm_mod.LLMError:
            continue
        quote, pos = _locate_quote_verbatim(text, str(obj.get("R_quote", "")))
        if pos < 0:
            # 模型引文不可回溯 → 不信任，用确定性首句锚点兜底
            quote = _first_sentence_quote(content, min(16, config["max_quote_chars"]))
        if not quote:
            continue
        steps = obj.get("A3_steps")
        steps = [str(s).strip() for s in steps if str(s).strip()] if isinstance(steps, list) else []
        if not steps:
            steps = ["确认适用条件", "按框架逐项检查", "给出带出处的结论或说明边界"]
        blocks.append({
            "title": str(obj.get("title") or heading).strip()[:24],
            "R_quote": quote,
            "I_rephrase": str(obj.get("I_rephrase") or "").strip()
            or f"按「{heading}」所界定的条件判断当前情境，再决定是否套用该方法。",
            "A1_author_case": str(obj.get("A1_author_case") or "").strip()
            or "该章节给出的原始说明（见出处）。",
            "A2_user_trigger": str(obj.get("A2_user_trigger") or "").strip()
            or f"当用户的问题涉及「{heading}」时触发。",
            "A3_steps": steps,
            "B_not_applicable": str(obj.get("B_not_applicable") or "").strip()
            or "不适用：书中未覆盖的问题，应明确回答「书里没讲」。",
        })
    return blocks


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


def extract_capabilities(full_text: str, segments: list[dict], config: dict,
                         book_title: str = "") -> dict:
    blocks = _parse_markup(full_text)
    extractor = "deterministic-markup"
    if not blocks:
        from .. import llm as llm_mod
        if llm_mod.available():
            blocks = _llm(full_text, segments, config, book_title)
            if blocks:
                extractor = "llm"
        if not blocks:
            blocks = _heuristic(full_text, segments,
                                quote_chars=min(16, config["max_quote_chars"]))
            extractor = "heuristic"

    tier, score = {"deterministic-markup": ("S", 0.9),
                   "llm": ("B", 0.7),
                   "heuristic": ("C", 0.4)}[extractor]
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
            "confidence": {"tier": tier, "score": score},
            "status": "draft",
        })

    return {
        "schema_version": "1.0",
        "book_sha256": "",  # filled by pipeline
        "extractor": extractor,
        "capabilities": caps,
    }
