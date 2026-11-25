"""宿主 Agent 承接通道：把 judge 工作导出成工单，由宿主 Agent 逐条判断。

为什么需要这条通道（以及为什么它比「让用户配 API key」好）
------------------------------------------------------------
BookLeme 是个 **harness**——它编排流程，但不自带大模型。真正做判断的智能体
就在现场：调用 `bookleme run` 的那个 Agent（WorkBuddy / Claude Code / Codex…）
本身就是大模型。让用户去配 `OPENAI_API_KEY` / `BOOKLEME_LLM_*`，等于让
被调用者自己去雇一个模型来做本来在场就能做的事——多一道配置、多一把密钥、
多一份泄露风险，还换不来任何质量。

所以分两半：

- **确定性那半留在 Python**：引文逐字回验、shingle 重叠、覆盖率、版权门——
  这些不需要模型，而且是 measured 指标。
- **主观那半交给宿主 Agent**：groundedness（断言是否真的被引文+上下文支持）、
  V2（预测力）、V3（独特性）本质是语义判断。宿主 Agent 用自己的推理能力
  逐条判，比绕一圈调外部 API 更直接、更省事，也不用用户配任何东西。

工作流：

    bookleme run --input <书>          # 编译；S5 自动导出工单
    bookleme judge --run-id <id>        # （可选）重新导出工单
    # 宿主 Agent 读工单 → 逐条判断 → 写 answers.json
    bookleme judge --apply <answers.json>   # 回填 → 指标变真值

`answers.json` 的结构见 ANSWERS_SCHEMA。回填走与在线 judge 完全相同的
`judge_capabilities` 归约逻辑（多数票、平票=未决），所以两种来源的指标
口径一致、可比。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from ..fidelity.judge import PERSONAS, _context, _majority, common_sense_hits, load_denylist

#: 宿主 Agent 回填的答案文件结构（自述，便于宿主照着填）。
ANSWERS_SCHEMA: dict = {
    "schema_version": "1.0",
    "description": (
        "宿主 Agent 的 judge 判定结果。每条 ability 对应一组 votes（每个 persona 一票），"
        "外加可选的 v2（预测力）判定。"
    ),
    "shape": {
        "judgments": {
            "<capability_id>": {
                "votes": [
                    {"persona": "考据员", "grounded": True, "support": "依据一句话",
                     "v3_pass": True, "v3_reason": "独特性理由"},
                ],
                "v2": {"v2_pass": True, "v2_question": "书里没明说的新问题",
                       "v2_answer": "依据该卡能否外推给出的答案"},
            },
        },
    },
}


def build_worklist(caps: dict, full_text: str, config: dict, *,
                   votes: int = 3, context_radius: int = 600) -> dict:
    """导出 judge 工单：每张能力卡 × 每个 persona 一条待判项。

    工单里带上**逐字引文**与**引文上下文原文**，让宿主 Agent 判「这句话是不是
    被原文支持的」时手上有全部证据——不需要它再去翻书稿。
    """
    denylist = load_denylist()
    effective_votes = max(1, min(int(votes), len(PERSONAS)))
    items: list[dict] = []
    for cap in caps.get("capabilities", []):
        cid = cap.get("capability_id", "")
        ria = cap.get("ria") or {}
        quote = ria.get("R_quote", "")
        ctx = _context(full_text, quote, context_radius,
                       (cap.get("span") or {}).get("char_start"))
        for role, persona in PERSONAS[:effective_votes]:
            items.append({
                "item_id": f"{cid}::{role}",
                "capability_id": cid,
                "kind": "grounded+v3",
                "persona": role,
                "persona_instruction": f"你是{role}。{persona}",
                "title": cap.get("title", ""),
                "quote": quote,
                "context": ctx,
                "rephrase": ria.get("I_rephrase", ""),
                "steps": " / ".join(str(s) for s in (ria.get("A3_steps") or [])),
                "not_applicable": ria.get("B_not_applicable", ""),
                "denylist_hits": common_sense_hits(ria.get("I_rephrase", ""), denylist),
                "answer_schema": {
                    "grounded": "bool — 断言是否真的被 quote+context 支持（只认字面证据）",
                    "support": "string — 一句话依据",
                    "v3_pass": "bool — 这条规则是否有区分度（换个书名就不成立 → false）",
                    "v3_reason": "string — 独特性判断的具体理由",
                },
            })
    return {
        "schema_version": "1.0",
        "kind": "judge_worklist",
        "generated_by": "bookleme (host-agent channel)",
        "instruction": (
            "你是本次编译的宿主 Agent，本身就是大模型——请逐条判断下面每个 item，"
            "按 answer_schema 输出 JSON，写进 answers.json 后执行 "
            "`bookleme judge --apply answers.json` 回填。"
            "只认字面证据：上下文没写明的要素一律判 grounded=false。"
        ),
        "answers_schema": ANSWERS_SCHEMA,
        "votes_requested": int(votes),
        "personas": [r for r, _ in PERSONAS[:effective_votes]],
        "items": items,
        "item_count": len(items),
    }


def apply_answers(caps: dict, answers: dict, config: dict) -> dict:
    """把宿主 Agent 的判定结果归约成与在线 judge 同构的结果字典。

    归约规则与 `fidelity.judge.judge_capabilities` 完全一致：
    - grounded：多数票；**平票 = 未决（None）**，不得记为 False
    - v3_pass：同样多数票
    - v2_pass：单条直接采信（可为 null）

    这样「宿主承接」与「在线调模型」两种来源的指标口径一致、可比。
    """
    judgments = answers.get("judgments") or {}
    denylist = load_denylist()
    results: dict[str, dict] = {}
    errors: list[str] = []
    for cap in caps.get("capabilities", []):
        cid = cap.get("capability_id", "")
        ria = cap.get("ria") or {}
        j = judgments.get(cid) or {}
        votes = j.get("votes") or []
        grounded_votes: list[bool] = []
        v3_votes: list[bool] = []
        supports: list[str] = []
        v3_reasons: list[str] = []
        for v in votes:
            if not isinstance(v, dict):
                continue
            if isinstance(v.get("grounded"), bool):
                grounded_votes.append(v["grounded"])
            if isinstance(v.get("v3_pass"), bool):
                v3_votes.append(v["v3_pass"])
            if v.get("support"):
                supports.append(str(v["support"])[:200])
            if v.get("v3_reason"):
                v3_reasons.append(str(v["v3_reason"])[:200])
        v2 = j.get("v2") or {}
        results[cid] = {
            "judged": bool(grounded_votes) or bool(v2) or bool(v3_votes),
            "grounded": _majority(grounded_votes),
            "grounded_votes": grounded_votes,
            "support": supports[0] if supports else "",
            "v2_pass": v2.get("v2_pass") if isinstance(v2.get("v2_pass"), bool) else None,
            "v2_question": str(v2.get("v2_question", ""))[:300],
            "v2_answer": str(v2.get("v2_answer", ""))[:300],
            "v3_pass": _majority(v3_votes),
            "v3_votes": v3_votes,
            "v3_reason": v3_reasons[0] if v3_reasons else "",
            "denylist_hits": common_sense_hits(ria.get("I_rephrase", ""), denylist),
        }
    judged = [r for r in results.values() if r["judged"]]
    error_types: dict[str, int] = {}
    for e in errors:
        name = e.split(":")[0].split("/")[-1].strip() or "unknown"
        error_types[name] = error_types.get(name, 0) + 1
    summary = {
        "capabilities": len(results),
        "judged": len(judged),
        "grounded": sum(1 for r in judged if r["grounded"] is True),
        "grounded_unknown": sum(1 for r in judged if r["grounded"] is None),
        "v2_pass": sum(1 for r in judged if r["v2_pass"] is True),
        "v2_unknown": sum(1 for r in judged if r["v2_pass"] is None),
        "v3_pass": sum(1 for r in judged if r["v3_pass"] is True),
        "v3_unknown": sum(1 for r in judged if r["v3_pass"] is None),
        "denylist_flagged": sum(1 for r in results.values() if r["denylist_hits"]),
        "failed_calls": len(errors),
        "error_types": error_types,
    }
    return {
        "enabled": True,
        "channel": "host_agent",
        # 指纹标注来源：宿主 Agent 承接 ≠ 某个外部模型。不得伪装成某家模型。
        "model_fingerprint": "host-agent",
        "prompt_version": "judge_v1+judge_v2_v1",
        "votes": max((len(r["grounded_votes"]) for r in results.values()), default=0),
        "votes_requested": len(PERSONAS),
        "results": results,
        "summary": summary,
        "errors": errors,
    }


def load_answers(path: Path) -> dict:
    """读宿主 Agent 写的 answers.json（宽容：也接受裸 {capability_id: {...}}）。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(data, dict) and "judgments" in data:
        return data
    if isinstance(data, dict):
        # 裸映射：{"C001": {...}} → 包一层
        return {"schema_version": "1.0", "judgments": data}
    raise ValueError("answers 文件格式不对：应为 {judgments: {...}} 或 {capability_id: {...}}")
