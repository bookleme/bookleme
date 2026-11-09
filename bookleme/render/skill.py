"""Deterministic skill-package renderer.

The SKILL.md five-section skeleton is generated HERE (not in plugins), so every
artifact satisfies the local skill convention by construction. Plugins supply
content: hard constraints, anti-patterns, output contract, voice, templates.
"""

from __future__ import annotations

import json
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
    )
    return "\n".join([
        "### Step 1：确认适用条件",
        "",
        f"检查用户请求是否落在触发场景内，并确认书中确实覆盖该问题。若数据或用户陈述不足，先追问，不用假设填充。",
        "",
        "### Step 2：定位框架",
        "",
        f"读取 `references/topic-index.md` 找到对应分片；{engine_note}",
        "",
        "### Step 3：按框架执行",
        "",
        "按分片中的 1-2-3 步骤执行，并保留作者的精确命名；每条判断都要带上处。",
        "",
        "### Step 4：产出具名结果并声明边界",
        "",
        "按「输出格式」给出带板块的结果，显式写出不适用条件与「还需要哪些数据」。",
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
    output_seed = Template(plugin.skill_template).safe_substitute(
        artifact=contract["artifact"],
        sections=" / ".join(contract["sections"]),
        min_tokens=contract.get("min_tokens", 0),
        max_tokens=contract.get("max_tokens", 0),
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
    return f"""---
name: {ctx['slug']}
description: {ctx['description']}
---

# {ctx['display_name']}

## 核心定位

{intro}

---

## 触发场景

{triggers}

---

## 工作流

{_steps(plugin, ctx)}

---

## 输出格式

{output_seed}

示例结构（正文按「必备板块」逐节产出；「元信息附录」是溯源层，两层都要交付）：

```
## {contract['artifact']}

{section_lines}

## 元信息附录
- 命中的框架：（名称 + 出处）
- 带出处的规则：（When X, do Y, because Z）
- 执行步骤：1. … 2. … 3. …
- 不适用边界：…
- 出处清单：segment_id / char_range
```

---

## Gotchas

{_gotchas(plugin, ctx)}
"""


def _framework_md(plugin, cap: dict, index: int) -> str:
    ria = cap["ria"]
    steps = "\n".join(f"{i}. {s}" for i, s in enumerate(ria["A3_steps"], 1))
    body = Template(plugin.section_template).safe_substitute(
        trigger=str(ria["A2_user_trigger"]).rstrip("。；;．. "),
        title=cap["title"], quote=ria["R_quote"],
        rephrase=ria["I_rephrase"], author_case=ria["A1_author_case"],
        steps=steps, not_applicable=ria["B_not_applicable"],
    )
    span = cap["span"]
    return (
        f"{body}\n"
        f"出处：{cap['source_id']} / {span['segment_id']} / char_range "
        f"[{span['char_start']}, {span['char_end']}) / 可信度 {cap['confidence']['tier']}\n"
    )


def render_skill(plugin, ctx: dict) -> dict[str, str]:
    caps = ctx["verified_capabilities"]
    files: dict[str, str] = {"SKILL.md": _skill_md(plugin, ctx)}

    rows = ["## 何时读本文件", "",
            "当用户问题需要定位到具体框架分片时，先读本表；不要一次性加载所有分片。", "",
            "| 用户问题 / 意图 | 读取文件 |", "| --- | --- |"]
    for i, cap in enumerate(caps, 1):
        rows.append(f"| {cap['title']} / {cap['ria']['A2_user_trigger']} | `references/framework-{i:02d}.md` |")
    rows += ["| 出处与版权 | `references/provenance.md` |"]
    files["references/topic-index.md"] = "\n".join(rows) + "\n"

    for i, cap in enumerate(caps, 1):
        files[f"references/framework-{i:02d}.md"] = _framework_md(plugin, cap, i)

    prov = ctx["provenance_manifest"]
    files["references/provenance.md"] = (
        "## 何时读本文件\n\n当需要核对来源、可信度或版权边界时读取本文件。\n\n"
        f"- 书名：{prov['book']['title']}\n- 作者：{prov['book']['author']}\n"
        f"- ISBN：{prov['book']['isbn']}\n- 使用权：{prov['book']['user_rights']}\n"
        f"- 分发决策：{prov['distribution']['decision']}（{prov['distribution']['reason']}）\n"
        f"- {prov['attribution']['statement']}\n- {prov['attribution']['notice']}\n"
        f"- 生成引擎：BookLeme {prov['engine']['bookleme_version']} / 插件 {prov['engine']['plugin_id']}\n"
    )

    if ctx["engine"] == "behavior_skill":
        contract = plugin.output_contract
        files["assets/blueprint-template.md"] = (
            f"# {contract['artifact']}（模板）\n\n"
            + "\n".join(f"## {s}\n\n（待填写）\n" for s in contract["sections"])
        )
        files["scripts/state_io.py"] = _STATE_IO
        files["state/schema.json"] = json.dumps(_STATE_SCHEMA, ensure_ascii=False, indent=2) + "\n"
        files["evals/smoke.md"] = (
            "# 冒烟用例\n\n"
            + "\n".join(
                f"- [{p['type']}] {p['id']}：{p['prompt']} → {p['expected_behavior']}"
                for p in plugin.eval_prompts
            )
            + "\n"
        )
        sm = getattr(plugin, "state_machine", None) or {}
        states = " / ".join(sm.get("states") or [])
        state_line = f"\ncurrent_state 取值：{states}。\n" if states else ""
        files["references/state-guide.md"] = (
            "## 何时读本文件\n\n需要实现可中断续聊或排查状态问题时读取。\n\n"
            f"{plugin.extra_sections.get('state_guide', '')}\n"
            f"{state_line}"
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
