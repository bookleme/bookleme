"""读图 → 能力卡：让视觉模型把图示里的信息提炼成可执行要点。

诚实约定（与本项目其它 LLM 环节一致）：

1. 视觉模型未配置 → 不调用，图只做「提取 + 交付」，**不产出解读**（不伪造）；
2. `R_quote` 用图注原文（逐字可溯，S1 已锚定到语料位置）；I/A/B 是**模型解读**，
   卡上以 `origin = "figure"`、`confidence.tier = "B"` 标明来源；
3. 模型读不到的地方由模型自述「无法辨认」，本模块不替它编；
4. 每张图一次调用；单图失败只丢这张图，不中断流水线；
5. 只处理「有位图 + 有逐字锚定图注」的图——没有逐字锚点就不做卡（无法溯源的卡不进产物）。
"""

from __future__ import annotations

import re

_SIX = ("R_quote", "I_rephrase", "A1_author_case", "A2_user_trigger",
        "A3_steps", "B_not_applicable")


def _render(template: str, values: dict) -> str:
    for key, val in values.items():
        template = template.replace("${" + key + "}", "" if val is None else str(val))
    return re.sub(r"\$\{[^}]+\}", "", template)


def _default_call(prompt_name: str, values: dict, image_path):
    from ..llm import chat_vision_json, load_prompt, split_prompt
    text = load_prompt(prompt_name)
    sys_part, user_part = split_prompt(text)
    return chat_vision_json(_render(user_part, values), system=_render(sys_part, values),
                            image_path=image_path)


def _context(full_text: str, caption: str, radius: int = 500) -> str:
    pos = full_text.find(caption)
    if pos < 0:
        return ""
    lo = max(0, pos - radius)
    hi = min(len(full_text), pos + len(caption) + radius)
    return full_text[lo:hi]


def _segment_for(pos: int, segments: list[dict]) -> str:
    if pos < 0:
        return "seg-000"
    for seg in segments:
        rng = seg.get("char_range") or []
        if len(rng) == 2 and rng[0] <= pos < rng[1]:
            return seg.get("segment_id", "seg-000")
    return segments[0].get("segment_id", "seg-000") if segments else "seg-000"


def extract_figure_cards(figures: list[dict], config: dict, book_title: str = "",
                         full_text: str = "", segments: list[dict] | None = None,
                         call=None) -> list[dict]:
    """为带位图且图注已锚定的图生成能力卡（读图 → 要点）。

    返回 capability 卡片列表（结构与 S4 抽取卡一致，可直接进 capabilities.json）。
    未配置视觉模型 / 无位图 / 无锚定图注 → 返回空列表（不产出任何解读）。
    """
    from ..config import ROOT
    from ..llm import model_fingerprint, vision_available

    cfg = config.get("figure_insight") or {}
    if not cfg.get("enabled", True):
        return []
    if not vision_available():
        return []
    call = call or _default_call
    limit = int(cfg.get("max_figures", 12))
    segments = segments or []
    out: list[dict] = []
    for fig in figures:
        if len(out) >= limit:
            break
        caption = (fig.get("caption") or "").strip()
        if fig.get("char_start") is None:
            continue                      # 无锚点 → 不做卡（无法溯源）
        if not fig.get("image_file"):
            continue                      # 无位图（矢量图）→ 无从读起
        image_path = ROOT / fig["image_file"]
        if not image_path.is_file():
            continue
        # R_quote 必须是语料里的逐字切片：图注本身在语料里就用图注（≤24 字前缀），
        # 否则（网页 alt 文本不在正文里）用语料锚点处的原文切片。
        # 判定以「切片是否真的出现在语料里」为准，不依赖 anchor_kind 字段。
        # 长度按本项目引文惯例收敛到 ≤24 字：图解读卡多达十余张，锚点过长会把
        # 总引文比顶过版权门上限（实测 60 字时 4.95% > 3%，门正确拦下）。
        quote_len = 24
        start = int(fig["char_start"])
        quote = ""
        if caption:
            probe = caption[:quote_len].strip()
            if probe and probe in full_text:
                quote = probe
        if not quote:
            quote = full_text[start:start + quote_len].strip()
        if len(quote) < 8:
            continue
        try:
            obj = call("figure_insight_v1", {
                "title": book_title or "未命名文献",
                "caption": caption or quote[:40],
                "context": _context(full_text, quote),
                "figure_id": fig["figure_id"],
                "page": fig.get("page") or "未标注",
            }, image_path)
        except Exception:
            continue                      # 单图失败只丢这张图
        if not isinstance(obj, dict):
            continue
        steps = obj.get("A3_steps")
        if isinstance(steps, str):
            steps = [steps]
        ria = {
            "R_quote": quote,
            "I_rephrase": str(obj.get("I_rephrase") or "").strip(),
            "A1_author_case": str(obj.get("A1_author_case") or "").strip(),
            "A2_user_trigger": str(obj.get("A2_user_trigger") or "").strip(),
            "A3_steps": [str(s).strip() for s in (steps or []) if str(s).strip()],
            "B_not_applicable": str(obj.get("B_not_applicable") or "").strip(),
        }
        if not ria["I_rephrase"] or not ria["A3_steps"]:
            continue                      # 六段不全 → 不进产物（S5 会判 rejected）
        idx = len(out) + 1
        quote_pos = full_text.find(quote)
        if quote_pos < 0:
            continue                      # 锚点切片不在语料里 → 弃卡（不伪造）
        char_start = quote_pos
        out.append({
            "capability_id": f"FIGCAP-{idx:03d}",
            "title": str(obj.get("title") or fig["figure_id"])[:40],
            "genre_tags": [],
            "engine_targets": ["knowledge_pack", "behavior_skill"],
            "source_id": fig.get("source_id", "SRC-001"),
            "span": {
                "segment_id": _segment_for(char_start, segments),
                "char_start": char_start,
                "char_end": char_start + len(quote),
                "section": _segment_for(char_start, segments),
                "page": fig.get("page") or 0,
                "chapter": "",
            },
            "ria": ria,
            "claims": [f"FIGCLM-{idx:03d}"],
            "checks": {"v1": [], "v2_predictive_q": "", "v2_pass": None,
                       "v3_uniqueness": None, "v3_pass": None},
            "confidence": {"tier": "B", "score": 0.7},
            "status": "draft",
            "figure_refs": [fig["figure_id"]],
            "origin": "figure",
            "figure_insight": {
                "figure_id": fig["figure_id"],
                "model_fingerprint": model_fingerprint("figure_insight_v1"),
                "prompt_version": "figure_insight_v1",
            },
        })
    return out
