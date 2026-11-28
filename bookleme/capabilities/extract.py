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

    句末标点必须同时认中文与英文：网页正文常是纯英文，若只认「。！？」
    就会一路切到下一个中文标点（整段没有 → 切到窗口上限），产出
    「Figure 1 shows R」这种半截引文（实测 microsoft.ai 页面 12 张卡全中）。
    """
    content = content.strip()
    if not content:
        return ""
    # 句末标点：中英文都认。英文句号后不能直接收口（会切在 "U.S." 里），
    # 所以要求其后不是字母（简单启发式，够用）。
    m = re.search(r"[。！？]", content)
    if m:
        sentence = content[:m.end()]
    else:
        sentence = ""
        for mm in re.finditer(r"[.!?](?=\s|$)", content):
            sentence = content[:mm.end()]
            break
        if not sentence:
            sentence = content
    # 短标签句要跳过：英文技术写作常用「Staleness. Agentic rollouts ...」
    # 这种「小标题句 + 正文句」结构。只取第一句会得到 'Staleness.'（10 字符，
    # 信息量不足以支撑能力卡）。规则：首句过短（<12 字符）且后面还有内容时，
    # 继续往后取一句。
    #
    # 逐字性是硬约束（find(quote) 必须命中原文）：拼接必须沿用原文的原始
    # 空白，不能自己补空格也不能自己删空格 —— 原文是 'Staleness. Agentic'，
    # 拼成 'Staleness.Agentic' 就不是原文子串了。
    while len(sentence.strip()) < 12:
        rest = content[len(sentence):]
        if not rest.strip():
            break
        stripped = rest.lstrip()
        nxt = ""
        for mm in re.finditer(r"[。！？]|[.!?](?=\s|$)", stripped):
            nxt = stripped[:mm.end()]
            break
        if not nxt:
            sentence = content
            break
        # 保留 rest 中句子之间的原始空白
        gap = rest[:len(rest) - len(stripped)]
        sentence = sentence + gap + nxt
    if len(sentence) <= quote_chars:
        return sentence.rstrip()
    window = sentence[:quote_chars + 8]
    # 从句边界：中文逗号顿号分号冒号 + 英文逗号分号（后跟空格）
    cuts = [mm.end() for mm in re.finditer(r"[，、；：]|[,;:](?=\s)", window) if mm.end() >= 8]
    if not cuts:
        # 没有从句边界 → 退到最近的词边界（英文）或空格
        if re.search(r"[A-Za-z0-9]$", window):
            sp = window.rfind(" ")
            if sp >= 8:
                cuts = [sp]
    quote = sentence[:cuts[-1]] if cuts else sentence[:quote_chars]
    return quote.rstrip().rstrip("，、；：,;:").rstrip()


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


def _genre_fields_block(genre_fields: dict) -> str:
    """体裁额外必填字段的说明块（写进抽取 prompt）。"""
    if not genre_fields:
        return "（本体裁无额外必填字段）"
    return "\n".join(f"- {name}：{desc}" for name, desc in genre_fields.items())


def _llm(text: str, segments: list[dict], config: dict, book_title: str,
         max_caps: int = 16, genre_fields: dict | None = None) -> list[dict]:
    """LLM 抽取：I/A/B 由模型深化，R_quote 终身逐字校验（失败即丢弃该卡）。

    单卡失败不中断：跳过该段继续；全军覆没时调用方回退 heuristic。
    `genre_fields` 是本体裁声明的额外必填字段（见 plugin.capability_schema）：
    模型必须逐个填写，书中没有的写「书里没讲」。
    """
    from .. import llm as llm_mod

    genre_fields = genre_fields or {}
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
                                   body=content[:_LLM_BODY_CHARS],
                                   genre_fields=_genre_fields_block(genre_fields))
        try:
            obj = llm_mod.chat_json(user, system=system)
        except llm_mod.LLMError:
            continue
        quote, pos = _locate_quote_verbatim(text, str(obj.get("R_quote", "")))
        if pos < 0:
            # 模型引文不可回溯 → 不信任，用确定性首句锚点兜底
            quote = _first_sentence_quote(content, min(28, config["max_quote_chars"]))
        if not quote:
            continue
        steps = obj.get("A3_steps")
        steps = [str(s).strip() for s in steps if str(s).strip()] if isinstance(steps, list) else []
        if not steps:
            steps = ["确认适用条件", "按框架逐项检查", "给出带出处的结论或说明边界"]
        raw_fields = obj.get("genre_fields")
        raw_fields = raw_fields if isinstance(raw_fields, dict) else {}
        filled = {}
        for name in genre_fields:
            val = str(raw_fields.get(name) or "").strip()
            filled[name] = val or "书里没讲"   # 缺失即如实标注，不编造
        safe_heading = _shorten_title(heading)
        blocks.append({
            "title": _shorten_title(str(obj.get("title") or heading), 24),
            "R_quote": quote,
            "I_rephrase": str(obj.get("I_rephrase") or "").strip()
            or f"按「{safe_heading}」所界定的条件判断当前情境，再决定是否套用该方法。",
            "A1_author_case": str(obj.get("A1_author_case") or "").strip()
            or "该章节给出的原始说明（见出处）。",
            "A2_user_trigger": str(obj.get("A2_user_trigger") or "").strip()
            or f"当用户的问题涉及「{safe_heading}」时触发。",
            "A3_steps": steps,
            "B_not_applicable": str(obj.get("B_not_applicable") or "").strip()
            or "不适用：书中未覆盖的问题，应明确回答「书里没讲」。",
            "genre_fields": filled,
        })
    return blocks


def _shorten_title(title: str, limit: int = 32) -> str:
    title = (title or "").strip()
    if len(title) <= limit:
        return title
    return title[: limit - 1] + "…"


def _heuristic(text: str, segments: list[dict], max_caps: int = 16, quote_chars: int = 28) -> list[dict]:
    """Low-confidence fallback: one card per heading, quote taken verbatim from source.

    引文预算：S7 版权门要求引文总量 ≤ 产物字符的 3%。每卡产物约 400 字符、
    固定部分约 2900 字符，16 卡时预算约 260 字符 → 每卡引文取 16 字以内
    （与合成样例 [CAP] 引文同量级）；完整溯源由 span.char_start 承担。

    为什么从 16 放宽到 28：16 字对英文技术写作信息量严重不足 —— 实测
    microsoft.ai 页面 12 张卡的引文全是 'Figure 1 shows R'、'Our largest RL r'
    这种半截话，无法支撑「带出处的规则」这一步。
    预算按版权门实测反推：产物 12,001 字 × 3% = 360 字，12 卡 → 每卡 ≤30 字。
    取 28 字留余量（实测 64 字时 ratio 0.0515 超门，28 字时约 0.023，稳过）。
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
        safe_title = _shorten_title(heading)
        blocks.append({
            "title": safe_title,
            "R_quote": first,
            "I_rephrase": f"按「{safe_title}」所界定的条件判断当前情境，再决定是否套用该方法。",
            "A1_author_case": "该章节给出的原始说明（见出处）。",
            "A2_user_trigger": f"当用户的问题涉及「{safe_title}」时触发。",
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
                         book_title: str = "",
                         genre_fields: dict | None = None,
                         host_blocks: list[dict] | None = None) -> dict:
    """抽取原子能力卡。

    `host_blocks`：宿主 Agent 承接抽取的结果（见 bookleme/judge/capability.py）。
    传了就直接用它 —— 这是「零配置拿到真内容」的通道：BookLeme 是 harness，
    在场调它的那个智能体本身就是大模型，让用户配 API key 让它自己调外部模型
    是把在场能做的事外包出去。
    """
    genre_fields = genre_fields or {}
    blocks = _parse_markup(full_text)
    extractor = "deterministic-markup"
    if host_blocks:
        blocks = host_blocks
        extractor = "host-agent"
    if not blocks:
        max_caps = int(config.get("max_capabilities", 16))
        from .. import llm as llm_mod
        if llm_mod.available():
            blocks = _llm(full_text, segments, config, book_title,
                          genre_fields=genre_fields, max_caps=max_caps)
            if blocks:
                extractor = "llm"
        if not blocks:
            blocks = _heuristic(full_text, segments, max_caps=max_caps,
                                quote_chars=min(28, config["max_quote_chars"]))
            extractor = "heuristic"

    tier, score = {"deterministic-markup": ("S", 0.9),
                   "host-agent": ("B", 0.7),
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
            # 体裁额外必填字段（plugin.capability_schema["genre_fields"]）：
            # LLM 抽取时由模型填写；确定性抽取路径填「书里没讲」——确定性抽取器
            # 本就拿不到阈值/矩阵这类结构化信息，如实标注而非留空或编造。
            "genre_fields": {name: (block.get("genre_fields", {}) or {}).get(name, "")
                             or "书里没讲" for name in genre_fields},
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


def attach_figure_refs(caps: dict, figures: list[dict], max_distance: int = 2000) -> None:
    """2.0 图挂接：最近能力卡（窗口内）——图注紧邻的讨论即配套对象。

    为什么不是「图注落在卡片 char 区间内」：能力卡 span 是引文句（十几字），
    图注是另一段文本，两者天然不重叠，区间包含永远挂不上（paper-2.0 实测教训）。
    规则：每个已锚定图挂到 char 距离最近的能力卡（等距偏向前方），距离超
    max_distance 则不挂（如实留空，不硬凑）。定位不到的图不挂任何卡。
    就地修改 caps；figure_refs 按图序号升序。
    """
    for cap in caps["capabilities"]:
        cap["figure_refs"] = []
    anchors = [(c, c["span"]["char_start"]) for c in caps["capabilities"]
               if isinstance(c["span"].get("char_start"), int)]
    for f in sorted(figures, key=lambda x: x["figure_id"]):
        fpos = f.get("char_start")
        if fpos is None or not anchors:
            continue
        best, best_d = None, None
        for cap, pos in anchors:
            d = abs(pos - fpos)
            if best_d is None or d < best_d or (d == best_d and pos <= fpos):
                best, best_d = cap, d
        if best is not None and best_d <= max_distance:
            best["figure_refs"].append(f["figure_id"])
