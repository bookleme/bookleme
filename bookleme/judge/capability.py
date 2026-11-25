"""宿主 Agent 承接 S4 能力卡抽取：把「这一节该提炼成什么能力卡」变成工单。

为什么必须有这条通道
--------------------
`capabilities/extract.py` 的 heuristic 抽取器只会填模板句：

    重写为可执行规则：按「Controlling staleness」所界定的条件判断当前情境，
    再决定是否套用该方法。

这种卡**没有知识**——它只告诉你「去读原文」，等于把检索的活推回给用户。
用户要的是结论，不是原文链接。

真正的 LLM 抽取器（`capability_extract_v1` prompt）能做对：把原文的方法论
提炼成「可执行规则 + 作者案例 + 触发语 + 步骤 + 不适用边界」。但它要调外部
API，于是又回到「用户得配密钥」的老问题。

宿主承接：把同一套契约交给在场的智能体，零配置拿到同样的产物。

契约与在线 LLM 路径**完全一致**（见 llm/prompts/capability_extract_v1.md）：
  - R_quote        逐字复制原文短语（8-24 字），是版权与溯源锚点
  - I_rephrase     把方法重写为可执行规则（40-80 字），禁与引文有 13 字连续重复
  - A1_author_case 书中案例/例证（30-80 字），保留可核查细节
  - A2_user_trigger 2-3 个真实用户话语样本
  - A3_steps       3-5 个执行步骤
  - B_not_applicable 不适用边界（20-60 字）
  - genre_fields   体裁额外必填字段，没有就写「书里没讲」
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..capabilities.extract import _heading_content_start

#: 宿主 Agent 回填的抽取结果结构。
ANSWERS_SCHEMA: dict = {
    "schema_version": "1.0",
    "description": "宿主 Agent 对每个章节的能力卡抽取结果。",
    "shape": {
        "cards": {
            "<segment_id>": {
                "title": "str — 作者对该方法的命名（≤20 字）",
                "R_quote": "str — 逐字复制原文的短语（8-24 字）",
                "I_rephrase": "str — 可执行规则（40-80 字）",
                "A1_author_case": "str — 书中案例（30-80 字）",
                "A2_user_trigger": "str — 2-3 个用户话语样本",
                "A3_steps": ["str", "..."],
                "B_not_applicable": "str — 不适用边界（20-60 字）",
                "genre_fields": {"字段名": "取值"},
            },
        },
    },
}

#: 契约里的硬约束（回填时校验）
#:
#: 长度口径按**语言自适应**，不按裸字符数：
#: - 中文书稿：「8-24 字」= 8-24 个汉字
#: - 英文书稿：「8-12 词」= 8-12 个单词（约 55-90 字符）
#:
#: 为什么不能统一按字符数：契约原文写的是「8-24 字」，那是按中文书稿的直觉写的。
#: 对英文技术书稿，24 个字符只有 4 个词（如 'We measure policy staleness'），
#: 作为溯源锚点几乎没有信息量。
#:
#: 为什么英文上限定 12 词：版权门第 2 条按**源文**刻度算（引文字数/源文字数
#: ≤3%）。以 25K 字的书、12 张卡反推，每卡引文上限约 63 字 ≈ 10-11 词。
#: 12 词留一点余量，又不至于被门拦下——引文是溯源锚点，也是版权计量的对象，
#: 两边必须一致，不能各说各话。
QUOTE_MIN_CHARS = 8        # 中文：最少字符
QUOTE_MAX_CHARS = 24       # 中文：最多字符
QUOTE_MIN_WORDS = 8        # 英文：最少词
QUOTE_MAX_WORDS = 12       # 英文：最多词

REPEAT_WINDOW = 13         # I_rephrase 与 R_quote 的最大连续重复长度
REPHrase_MIN_CHARS = 40    # 中文：最少字符
REPHrase_MAX_CHARS = 80    # 中文：最多字符
REPHrase_MIN_WORDS = 20    # 英文：最少词
REPHrase_MAX_WORDS = 50    # 英文：最多词


def _is_cjk_heavy(s: str) -> bool:
    """判断文本是否以中文为主（决定用哪套长度口径）。"""
    cjk = sum(1 for ch in s if "一" <= ch <= "鿿")
    letters = sum(1 for ch in s if ch.isalpha())
    return cjk * 2 >= max(1, letters)


def _zh_len(s: str) -> int:
    """中文语义长度：**去掉标点与空白**后的实字数。

    为什么不用 len()：中文标点（，。；：「」）在 len() 里各占 1，但读者感知
    的是「多少个实字」。按 len() 计，一条 80 字的规则若含 15 个标点，实际
    只有 65 个实字——会被误判成超长，逼着写作者去砍内容，而不是去提密度。
    """
    return sum(1 for ch in s if ch.strip() and not _is_punct(ch))


def _is_punct(ch: str) -> bool:
    import unicodedata
    return unicodedata.category(ch).startswith("P") or ch in "，。；：、「」『』（）—…·"


def _display_width(s: str) -> int:
    """视觉宽度：CJK 全角算 2，其余算 1。"""
    import unicodedata
    w = 0
    for ch in s:
        w += 2 if unicodedata.east_asian_width(ch) in ("F", "W") else 1
    return w


def build_worklist(text: str, segments: list[dict], book_title: str, *,
                   genre_fields: dict | None = None, body_chars: int = 3000) -> dict:
    """导出能力卡抽取工单：每个章节一条待填项。

    工单里给的是**章节正文全文**（截到 body_chars）——宿主要提炼出方法论，
    就必须看到原文，不能只看到标题。
    """
    genre_fields = genre_fields or {}
    gf_block = "\n".join(f"- {name}：{desc}" for name, desc in genre_fields.items()) \
        or "（本体裁无额外必填字段）"
    items: list[dict] = []
    for seg in segments:
        start, end = seg["char_range"]
        body = text[start:end]
        heading = seg["heading"].strip()
        content = body[_heading_content_start(body, heading):].strip()
        if not content:
            continue
        items.append({
            "item_id": seg.get("segment_id", ""),
            "segment_id": seg.get("segment_id", ""),
            "heading": heading,
            "title_hint": heading,
            "body": content[:body_chars],
            "body_truncated": len(content) > body_chars,
            "genre_fields": {name: desc for name, desc in genre_fields.items()},
        })
    return {
        "schema_version": "1.0",
        "kind": "capability_extract_worklist",
        "generated_by": "bookleme (host-agent channel)",
        "book_title": book_title,
        "instruction": (
            "你是本次编译的宿主 Agent，本身就是大模型。请为每个章节提炼一张"
            "「原子能力卡」——读者能直接执行的方法单元，而不是「去读原文」的指路牌。"
        ),
        "rules": [
            "R_quote 逐字复制原文短语（中文 8-24 字 / 英文 8-12 词），不得改写、"
            "不得合并换行、不得增删字符——它是版权与溯源锚点。",
            f"I_rephrase 把方法重写为可执行规则（中文 40-80 字 / 英文 20-50 词），"
            f"禁止复制 R_quote 原句，禁止与 R_quote 有 {REPEAT_WINDOW} 字以上连续重复。",
            "A1_author_case 转述书中具体案例/例证（中文 30-80 字 / 英文 15-45 词），"
            "保留人物、数字、情境等可核查细节；书中没有案例时写「本章未给出具体案例」。",
            "A2_user_trigger 写 2-3 个真实用户话语样本（每句 ≤20 字），形如"
            "「当用户说『……』时」。",
            "A3_steps 写 3-5 个执行步骤，至少一步是具体的提问或自检动作。",
            "B_not_applicable 写不适用边界（中文 20-60 字 / 英文 10-30 词）："
            "什么情况下不该套用本方法。",
            "只写本章实际讲过的内容。书里没有的绝不编造；宁可少写，不可虚构。",
        ],
        "genre_fields_block": gf_block,
        "answers_schema": ANSWERS_SCHEMA,
        "items": items,
        "item_count": len(items),
    }


def validate_card(card: dict, body: str, genre_fields: dict | None = None) -> tuple[bool, str]:
    """校验一张卡是否满足契约。返回 (是否通过, 失败原因)。

    校验项与在线 LLM 路径一致：引文必须逐字在原文里；I_rephrase 不能是
    引文的复读；长度下限防止「空话卡」蒙混过关。
    """
    genre_fields = genre_fields or {}
    quote = str(card.get("R_quote") or "").strip()
    if not quote:
        return False, "R_quote 为空"
    if _is_cjk_heavy(quote):
        if not (QUOTE_MIN_CHARS <= _zh_len(quote) <= QUOTE_MAX_CHARS):
            return False, (f"R_quote 实字数 {_zh_len(quote)} 不在 "
                           f"{QUOTE_MIN_CHARS}-{QUOTE_MAX_CHARS} 内：{quote[:40]!r}")
    else:
        words = len(quote.split())
        if not (QUOTE_MIN_WORDS <= words <= QUOTE_MAX_WORDS):
            return False, (f"R_quote 词数 {words} 不在 "
                           f"{QUOTE_MIN_WORDS}-{QUOTE_MAX_WORDS} 内：{quote[:40]!r}")
    if body and quote not in body:
        return False, f"R_quote 不是原文逐字子串：{quote[:40]!r}"

    rephrase = str(card.get("I_rephrase") or "").strip()
    if _is_cjk_heavy(rephrase):
        if not (REPHrase_MIN_CHARS <= _zh_len(rephrase) <= REPHrase_MAX_CHARS):
            return False, (f"I_rephrase 实字数 {_zh_len(rephrase)} 不在 "
                           f"{REPHrase_MIN_CHARS}-{REPHrase_MAX_CHARS} 内")
    else:
        rwords = len(rephrase.split())
        if not (REPHrase_MIN_WORDS <= rwords <= REPHrase_MAX_WORDS):
            return False, (f"I_rephrase 词数 {rwords} 不在 "
                           f"{REPHrase_MIN_WORDS}-{REPHrase_MAX_WORDS} 内")
    if _max_common_run(quote, rephrase) >= REPEAT_WINDOW:
        return False, (f"I_rephrase 与 R_quote 有 {REPEAT_WINDOW} 字以上连续重复"
                       "（照抄原文等于没提炼）")

    steps = card.get("A3_steps")
    if not isinstance(steps, list) or len(steps) < 2:
        return False, "A3_steps 少于 2 步"
    if not str(card.get("B_not_applicable") or "").strip():
        return False, "B_not_applicable 为空"
    for name in genre_fields:
        val = card.get("genre_fields", {})
        if not isinstance(val, dict) or not str(val.get(name) or "").strip():
            return False, f"体裁必填字段 {name} 缺失"
    return True, ""


def _max_common_run(a: str, b: str) -> int:
    """a 与 b 的最长公共连续子串长度（用于查「照抄原文」）。"""
    if not a or not b:
        return 0
    # 用后缀自动机的简化版：滚动 DP
    prev = [0] * (len(b) + 1)
    best = 0
    for i in range(1, len(a) + 1):
        cur = [0] * (len(b) + 1)
        for j in range(1, len(b) + 1):
            if a[i - 1] == b[j - 1]:
                cur[j] = prev[j - 1] + 1
                if cur[j] > best:
                    best = cur[j]
        prev = cur
    return best


def apply_answers(text: str, segments: list[dict], answers: dict, *,
                   genre_fields: dict | None = None) -> tuple[list[dict], list[dict]]:
    """把宿主填的能力卡回填成 blocks 列表。

    返回 (blocks, rejected)：blocks 是可直接进能力卡流水线的抽取结果；
    rejected 列出未通过校验的卡（含原因）——**如实报告，不静默丢弃**。
    """
    genre_fields = genre_fields or {}
    cards = answers.get("cards") or {}
    seg_by_id = {s.get("segment_id", ""): s for s in segments}
    blocks: list[dict] = []
    rejected: list[dict] = []
    for seg_id, card in cards.items():
        seg = seg_by_id.get(seg_id)
        if seg is None:
            rejected.append({"segment_id": seg_id, "reason": "找不到对应章节"})
            continue
        start, end = seg["char_range"]
        body = text[start:end]
        heading = seg["heading"].strip()
        ok, why = validate_card(card, body, genre_fields)
        if not ok:
            rejected.append({"segment_id": seg_id, "heading": heading, "reason": why})
            continue
        steps = [str(s).strip() for s in (card.get("A3_steps") or []) if str(s).strip()]
        raw_fields = card.get("genre_fields")
        raw_fields = raw_fields if isinstance(raw_fields, dict) else {}
        filled = {}
        for name in genre_fields:
            val = str(raw_fields.get(name) or "").strip()
            filled[name] = val or "书里没讲"   # 缺失即如实标注，不编造
        blocks.append({
            "title": str(card.get("title") or heading).strip()[:24],
            "R_quote": str(card.get("R_quote")).strip(),
            "I_rephrase": str(card.get("I_rephrase")).strip(),
            "A1_author_case": str(card.get("A1_author_case") or "").strip()
            or "本章未给出具体案例。",
            "A2_user_trigger": str(card.get("A2_user_trigger") or "").strip()
            or f"当用户说「{heading}」时触发。",
            "A3_steps": steps,
            "B_not_applicable": str(card.get("B_not_applicable") or "").strip(),
            "genre_fields": filled,
            "_segment_id": seg_id,
        })
    return blocks, rejected


def load_answers(path: Path) -> dict:
    """读宿主写的抽取答案（宽容：也接受裸 {segment_id: {...}}）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "cards" in data:
        return data
    if isinstance(data, dict):
        return {"schema_version": "1.0", "cards": data}
    raise ValueError("抽取答案格式不对：应为 {cards: {...}} 或 {segment_id: {...}}")
