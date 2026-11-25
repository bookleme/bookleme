"""Deterministic skill-package renderer.

The SKILL.md five-section skeleton is generated HERE (not in plugins), so every
artifact satisfies the local skill convention by construction. Plugins supply
content: hard constraints, anti-patterns, output contract, voice, templates.
"""

from __future__ import annotations

import json
from pathlib import Path
from string import Template

from .description import build_description

_STATE_IO = '''"""Minimal cross-turn state helper. Runtime state lives outside the skill package."""
import json
import os
from pathlib import Path


def default_state_dir():
    """Runtime state root: BOOKLEME_STATE_DIR env var, else ~/.bookleme/sessions."""
    return os.environ.get("BOOKLEME_STATE_DIR") or str(Path.home() / ".bookleme" / "sessions")


def state_path(slug, session_id, state_dir=None):
    return Path(state_dir or default_state_dir()) / slug / session_id / "state.json"


def load(slug, session_id, state_dir=None):
    p = state_path(slug, session_id, state_dir)
    if not p.exists():
        return {"slug": slug, "session_id": session_id, "current_state": "opening",
                "turn_index": 0, "asked_questions": [], "answers": [],
                "skipped_reverse": [], "version": 1}
    with p.open("r", encoding="utf-8") as fh:
        return json.load(fh)


def save(state, slug, session_id, state_dir=None):
    p = state_path(slug, session_id, state_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_name("state.json.tmp")
    with tmp.open("w", encoding="utf-8") as fh:
        json.dump(state, fh, ensure_ascii=False, indent=2)
    os.replace(tmp, p)
'''

_STATE_SCHEMA = {
    "type": "object",
    "required": ["slug", "session_id", "current_state", "turn_index"],
    "properties": {
        "slug": {"type": "string"}, "session_id": {"type": "string"},
        "current_state": {"type": "string"}, "turn_index": {"type": "integer"},
        "asked_questions": {"type": "array"}, "answers": {"type": "array"},
        "skipped_reverse": {"type": "array"}, "version": {"type": "integer"},
    },
}


def _steps(plugin, ctx: dict) -> str:
    engine_note = (
        "按 Topic Index 路由到对应 references/ 分片，只加载当前问题需要的那一份。"
        if ctx["engine"] == "knowledge_pack"
        else "按状态机推进：每轮只问一题，读完回答后先做简短反馈再进入下一题；"
             "每轮结束把 current_state / asked_questions / answers 写入 state.json"
             "（用 `scripts/state_io.py`，约定见 `references/state-guide.md`）。"
             "完整多轮会话先读 `references/session-map.md` 取默认阶段序与题目预算。"
    )
    step4_note = (
        "正文骨架用 `assets/blueprint-template.md`，交付前对照其中的「必备字段核对」。"
        if ctx["engine"] == "behavior_skill" else ""
    )
    figures = ctx.get("figures") or []
    fig_note = ""
    if figures:
        n_img = sum(1 for f in figures if f.get("image_file"))
        fig_note = (
            f"若问题涉及图里的结构/流程/数据，先按 `references/figures-index.md` 取图"
            f"（{n_img} 张位图在 `assets/figures/`）并**用你的视觉能力读图**，"
            f"作答注明「依据 FIG-XXX（原文 p.N）」；图里看不清就明说「图中此处无法辨认」。"
        )
    coverage_note = (
        "先读 `references/coverage.md`（原文目录）确认本书覆盖哪些章节——覆盖范围是有据可查的，"
        "不要凭印象判断「这本书大概会讲」。"
        if ctx.get("toc") else ""
    )
    return "\n".join([
        "### Step 1：确认适用条件",
        "",
        f"检查用户请求是否落在触发场景内，并确认书中确实覆盖该问题。若数据或用户陈述不足，先追问，不用假设填充。"
        + (f"\n{coverage_note}" if coverage_note else ""),
        "",
        "### Step 2：定位框架",
        "",
        f"读取 `references/topic-index.md` 找到对应分片；{engine_note}",
        "",
        "### Step 3：按框架执行",
        "",
        "按分片中的 1-2-3 步骤执行，并保留作者的精确命名；每条判断都要带上出处。"
        + (f"\n{fig_note}" if fig_note else ""),
        "",
        "### Step 4：产出具名结果并声明边界",
        "",
        f"按「输出格式」给出带板块的结果，显式写出不适用条件与「还需要哪些数据」。{step4_note}",
        "",
        "### Step 5：遇到书中未覆盖的问题",
        "",
        "明确回答「书里没讲」并说明能力边界，不编造章节、出处或结论。若属于心理/医疗/法律/投资等专业判断，提示寻求有资质的专业人士。",
    ])


def _gotchas(plugin, ctx: dict) -> str:
    lines = [f"- {c}" for c in plugin.hard_constraints]
    lines += [f"- 反模式：{a}" for a in plugin.anti_patterns]
    lines += [
        "- 书中未涉及的问题必须回答「书里没讲」，不得编造出处；这不是能力缺陷而是忠实度要求。",
        f"- 版权：本技能是《{ctx['book_title']}》的结构化衍生笔记，不含原书段落，非原书替代品；版权与商标归原权利人所有。仅供学习，支持正版。",
        f"- 数据依赖：{plugin.extra_sections.get('data_dependency', '不绑定任何专有数据库。')}",
        "- 错误路径：无法定位框架或证据不足时，回到 Step 1 追问，不要硬套框架。",
    ]
    return "\n".join(lines)


def _skill_md(plugin, ctx: dict) -> str:
    contract = plugin.output_contract
    min_c = contract.get("min_chars", contract.get("min_tokens", 0))
    max_c = contract.get("max_chars", contract.get("max_tokens", 0))
    output_seed = Template(plugin.skill_template).safe_substitute(
        artifact=contract["artifact"],
        sections=" / ".join(contract["sections"]),
        min_chars=min_c,
        max_chars=max_c,
        min_tokens=min_c,
        max_tokens=max_c,
        verdict_ownership=plugin.voice_calibration["verdict_ownership"],
    )
    triggers = "\n".join(f"- 当用户说「{w}」或提出相关问题时" for w in plugin.trigger_words)
    intro = (
        f"本技能把《{ctx['book_title']}》中可复用的方法编译成「{plugin.display_name_zh}」流程，"
        "供你在真实问题里反复调用。它是结构化衍生笔记，不含原书段落，也不是原书替代品。"
        f"适用于 {', '.join(plugin.trigger_words)} 等场景；"
        "不适用于书中未覆盖的问题，以及需要专业资质判断的心理、医疗、法律、投资场景。"
    )
    section_lines = "\n\n".join(f"### {s}\n\n（回引用户自述的结论）" for s in contract["sections"])
    # 方法主线：直接从原文目录取，不做概括——让读者一眼看出这本书讲的是什么路线，
    # 而不是只看到一句「本技能把某某编译成流程」的模板话术。
    arc = ""
    toc_heads = [str(e.get("heading", "")).strip() for e in (ctx.get("toc") or [])
                 if int(e.get("level", 1)) <= 2 and str(e.get("heading", "")).strip()]
    # Markdown 的 H1 常常就是书名本身，重复一次没有信息量
    if toc_heads and toc_heads[0] == str(ctx.get("book_title", "")).strip():
        toc_heads = toc_heads[1:]
    if len(toc_heads) >= 2:
        shown = toc_heads[:8]
        tail = " → …" if len(toc_heads) > len(shown) else ""
        arc = "\n\n**方法主线**（取自原文目录）：" + " → ".join(shown) + tail
    meta_bullets = ("- 命中的框架：（名称 + 出处）\n- 带出处的规则：（When X, do Y, because Z）\n"
                    "- 执行步骤：1. … 2. … 3. …\n- 不适用边界：…\n- 出处清单：segment_id / char_range")
    meta_fields = ["命中的框架", "带出处的规则", "执行步骤", "不适用边界", "出处清单"]
    if list(contract["sections"]) == meta_fields:
        # 板块本身即溯源元信息（速查类产物）：单示例即可，不设元信息附录
        example_block = f"示例结构：\n\n```\n## {contract['artifact']}\n{meta_bullets}\n```"
    else:
        example_block = (
            "示例结构（正文按「必备板块」逐节产出；「元信息附录」是溯源层，两层都要交付）：\n\n"
            f"```\n## {contract['artifact']}\n\n{section_lines}\n\n"
            f"## 元信息附录\n{meta_bullets}\n```"
        )
    notes = []
    if contract.get("required_fields"):
        notes.append(f"必备字段（缺一不可）：{' / '.join(contract['required_fields'])}。")
    if contract.get("file_name"):
        notes.append(f"交付约定：以 Markdown 文件落盘（模板名 `{contract['file_name']}`，"
                     f"建议命名 `<产物名>_<YYYY-MM-DD>.md`），交付时给出完整文件绝对路径。")
    notes_block = ("\n" + "\n".join(notes) + "\n") if notes else ""
    return f"""---
name: {ctx['slug']}
description: {ctx['description']}
---

# {ctx['display_name']}

## 核心定位

{intro}{arc}

---

## 触发场景

{triggers}

---

## 工作流

{_steps(plugin, ctx)}

---

## 输出格式

{output_seed}{notes_block}
{example_block}

---

## Gotchas

{_gotchas(plugin, ctx)}
"""


def _framework_md(plugin, cap: dict, index: int, figures: dict | None = None) -> str:
    ria = cap["ria"]
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(ria["A3_steps"], 1))
    # 体裁额外必填字段（plugin.capability_schema.genre_fields）参与模板替换：
    # 标准 RIA 字段优先，体裁字段只补空位，避免同名覆盖。
    subst = {
        "trigger": str(ria["A2_user_trigger"]).rstrip("。；;．. "),
        "title": cap["title"], "quote": ria["R_quote"],
        "rephrase": ria["I_rephrase"], "author_case": ria["A1_author_case"],
        "steps": steps, "not_applicable": ria["B_not_applicable"],
    }
    genre_fields = cap.get("genre_fields") or {}
    for key, val in genre_fields.items():
        subst.setdefault(str(key), str(val))
    body = Template(plugin.section_template).safe_substitute(**subst)
    span = cap["span"]
    gf_block = ""
    if genre_fields:
        gf_lines = ["\n## 体裁必填字段\n"]
        for key, val in genre_fields.items():
            gf_lines.append(f"- **{key}**：{val}")
        gf_block = "\n".join(gf_lines) + "\n"
    fig_block = ""
    refs = cap.get("figure_refs") or []
    if refs and figures:
        lines = ["\n## 配套图示\n"]
        for fid in refs:
            f = figures.get(fid)
            if not f:
                continue
            if f.get("image_file"):
                rel = f"assets/figures/{fid}{Path(f['image_file']).suffix}"
            else:
                rel = "仅图注（矢量图/无可提取位图）"
            page = f"原文 p.{f['page']}，" if f.get("page") else ""
            lines.append(f"- {fid}（{rel}，{page}可逐字追溯）")
        lines.append("  图注原文不复制入产物（版权纪律）；见共享 IR figures.json / figures-index.md。")
        fig_block = "\n".join(lines) + "\n"
    return (
        f"{body}\n"
        f"{gf_block}"
        f"{fig_block}"
        f"出处：{cap['source_id']} / {span['segment_id']} / char_range "
        f"[{span['char_start']}, {span['char_end']}) / 可信度 {cap['confidence']['tier']}\n"
    )


def render_skill(plugin, ctx: dict) -> dict[str, str]:
    caps = ctx["verified_capabilities"]
    figs = {f["figure_id"]: f for f in ctx.get("figures", [])}
    files: dict[str, str] = {"SKILL.md": _skill_md(plugin, ctx)}

    rows = ["## 何时读本文件", "",
            "当用户问题需要定位到具体框架分片时，先读本表；不要一次性加载所有分片。", "",
            "| 用户问题 / 意图 | 读取文件 |", "| --- | --- |"]
    # 同名卡（模型常给出相似标题）必须可区分，否则这张表等于没路由价值
    seen: dict[str, int] = {}
    for i, cap in enumerate(caps, 1):
        title = str(cap["title"]).strip() or f"能力 {i}"
        n = seen.get(title, 0)
        seen[title] = n + 1
        if n or seen[title] > 1:
            tag = "、".join(cap.get("figure_refs") or []) or f"#{i}"
            title = f"{title}（{tag}）"
        rows.append(f"| {title} / {cap['ria']['A2_user_trigger']} | `references/framework-{i:02d}.md` |")
    if ctx.get("toc"):
        rows.append("| 这本书到底覆盖什么（判断该不该答） | `references/coverage.md` |")
    if figs:
        rows.append("| 原书图示 / 图示索引 | `references/figures-index.md` |")
    if ctx.get("engine") == "knowledge_pack":
        # 这两个文件此前生成但没人指路，等于死文件——挂进索引
        rows.append("| 快速判断表（当用户问『先看哪条』） | `references/cheatsheet.md` |")
        rows.append("| 三级按需加载怎么用 | `references/index-guide.md` |")
    rows += ["| 出处与版权 | `references/provenance.md` |"]
    files["references/topic-index.md"] = "\n".join(rows) + "\n"

    for i, cap in enumerate(caps, 1):
        files[f"references/framework-{i:02d}.md"] = _framework_md(plugin, cap, i, figs)

    if figs:
        flines = ["## 何时读本文件", "",
                  "需要查看原书图示（方法结构图/表格等）时读取本表，再到 assets/figures/ 取图。", "",
                  "| 图 ID | 类型 | 锚定状态 | 资产 | 出处 |", "| --- | --- | --- | --- | --- |"]
        for f in figs.values():
            if f.get("image_file"):
                rel = f"`assets/figures/{f['figure_id']}{Path(f['image_file']).suffix}`"
            else:
                rel = "仅图注（矢量图/无可提取位图）"
            if f.get("char_start") is not None:
                status = f"已锚定 p.{f['page']}" if f.get("page") else "已锚定"
            else:
                status = "未锚定"
            page = f"p.{f['page']}" if f.get("page") else "—"
            if f.get("unlabeled"):
                status += "（无图注）"
            if f.get("pairing_uncertain"):
                status += "（图注与位图按序配对，仅供参考）"
            flines.append(f"| {f['figure_id']} | {f['kind']} | {status} | {rel} | {f['source_id']} / {page} |")
        flines += ["",
                   "图注原文不复制进产物（版权纪律）：逐字图注与精确位置存于共享 IR `figures.json`，",
                   "需要图注时回读 IR 或原书对应页，不要凭印象转述。",
                   "",
                   "## 读图任务（多模态按需执行）",
                   "",
                   "本包里的图示要**亲自看图**才能用上信息，不要只凭图注推测：",
                   "",
                   "1. 用户的问题可能涉及图里的结构、流程或数据 → 按上表取图"
                   "（`assets/figures/FIG-XXX.png`），用你的视觉能力读图；",
                   "2. 读图后作答要注明「依据 FIG-XXX（原文 p.N）」，让结论可回溯；",
                   "3. 图里看不清或没有对应图时，明说「图中此处无法辨认」/「书里没讲」，不要猜。",
                   "",
                   "版权提示：图示为原书/原文图片，仅供个人学习检索，非自有/公版时禁止随产物公开分发。"]
        files["references/figures-index.md"] = "\n".join(flines) + "\n"

    # 覆盖范围：让智能体在「书里到底有没有」这件事上有据可依，而不是凭感觉外推。
    # 只由原文目录生成，不做任何推断，所以可以放心当边界依据。
    toc = ctx.get("toc") or []
    if toc:
        entries = [e for e in toc
                   if str(e.get("heading", "")).strip() != str(ctx.get("book_title", "")).strip()]
        lines = ["## 何时读本文件", "",
                 "当用户的问题可能不在本书范围内时，先读本文件确认覆盖范围。", "",
                 "## 本书覆盖的章节（取自原文目录）", ""]
        for e in entries[:120]:
            level = max(1, min(int(e.get("level", 1)), 4))
            lines.append(f"{'  ' * (level - 1)}- {e.get('heading', '').strip()}")
        lines += ["", "## 怎么用", "",
                  "- 问题落在上面这些章节之内 → 按 `references/topic-index.md` 定位分片作答，并给出处。",
                  "- 落在范围之外 → 直接说「书里没讲」，不要拿通用知识冒充书里的方法；",
                  "  用户明确要你的通用看法时，也要标注「这不是书里的内容」。"]
        files["references/coverage.md"] = "\n".join(lines) + "\n"

    prov = ctx["provenance_manifest"]
    fig_line = ""
    if figs:
        fig_line = (f"- 图示：共 {len(figs)} 个"
                    f"（带图 {sum(1 for f in figs.values() if f.get('image_file'))}，"
                    f"仅图注 {sum(1 for f in figs.values() if not f.get('image_file'))}），"
                    "图片资产在 assets/figures/，图注逐字锚定见 figures-index.md\n")
    files["references/provenance.md"] = (
        "## 何时读本文件\n\n当需要核对来源、可信度或版权边界时读取本文件。\n\n"
        f"- 书名：{prov['book']['title']}\n- 作者：{prov['book']['author']}\n"
        f"- ISBN：{prov['book']['isbn']}\n- 使用权：{prov['book']['user_rights']}\n"
        f"- 分发决策：{prov['distribution']['decision']}（{prov['distribution']['reason']}）\n"
        f"{fig_line}"
        f"- {prov['attribution']['statement']}\n- {prov['attribution']['notice']}\n"
        f"- 生成引擎：BookLeme {prov['engine']['bookleme_version']} / 插件 {prov['engine']['plugin_id']}\n"
    )

    # 自测用例对所有体裁都生成：速查类也要能回答「书里没讲」与边界问题，
    # 缺了它，产物改完没有任何可回归的判据（`bookleme check` 会为此报薄）。
    files["evals/smoke.md"] = (
        "# 冒烟用例\n\n"
        + "\n".join(
            f"- [{p['type']}] {p['id']}：{p['prompt']} → {p['expected_behavior']}"
            for p in plugin.eval_prompts
        )
        + "\n"
    )

    if ctx["engine"] == "behavior_skill":
        contract = plugin.output_contract
        fields = contract.get("required_fields") or []
        field_block = ("\n## 必备字段核对\n\n" + "\n".join(f"- [ ] {f}" for f in fields) + "\n") if fields else ""
        files["assets/blueprint-template.md"] = (
            f"# {contract['artifact']}（模板）\n\n"
            + "\n".join(f"## {s}\n\n（待填写）\n" for s in contract["sections"])
            + field_block
        )
        files["scripts/state_io.py"] = _STATE_IO
        files["state/schema.json"] = json.dumps(_STATE_SCHEMA, ensure_ascii=False, indent=2) + "\n"
        sm = getattr(plugin, "state_machine", None) or {}
        states = " / ".join(sm.get("states") or [])
        state_line = f"\ncurrent_state 取值：{states}。\n" if states else ""
        files["references/state-guide.md"] = (
            "## 何时读本文件\n\n需要实现可中断续聊或排查状态问题时读取。\n\n"
            f"{plugin.extra_sections.get('state_guide', '')}\n"
            f"{state_line}"
        )
        session_map = plugin.extra_sections.get("session_map")
        if session_map:
            files["references/session-map.md"] = (
                "## 何时读本文件\n\n多轮完整会话开始前与中断恢复时读取。\n\n"
                f"{session_map}\n"
            )
    else:
        lines = ["## 何时读本文件", "", "需要快速判断「什么情境用哪条规则」时读取本文件。", "",
                 "## 决策规则", ""]
        for cap in caps:
            lines.append(f"- 当 {cap['ria']['A2_user_trigger']} → {cap['ria']['I_rephrase']}")
            lines.append(f"  - 不适用：{cap['ria']['B_not_applicable']}")
        files["references/cheatsheet.md"] = "\n".join(lines) + "\n"
        files["references/index-guide.md"] = (
            "## 何时读本文件\n\n需要理解三级按需加载策略时读取。\n\n"
            f"{plugin.extra_sections.get('index_guide', '')}\n"
        )

    return files
