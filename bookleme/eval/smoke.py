"""Deterministic smoke tests. The negative case must refuse to answer."""

from __future__ import annotations

import re
from pathlib import Path

_CATCH_ALL = ["任何问题", "所有任务", "万能", "一切问题"]


def run_smoke(skill_dir: Path, plugin, description: str,
              capabilities: list[dict], validation_report: dict) -> dict:
    skill_dir = Path(skill_dir)
    text = "\n".join(
        p.read_text(encoding="utf-8", errors="replace")
        for p in sorted(skill_dir.rglob("*"))
        if p.is_file() and p.suffix in {".md", ".py", ".json"}
    )
    titles = [c["title"] for c in capabilities]
    hits = [w for w in plugin.trigger_words if w in description]

    cases = {
        "positive": {
            "passed": any(t and t in text for t in titles),
            "detail": "产物中至少出现一个已验证框架名",
        },
        "negative_unanswered": {
            "passed": "书里没讲" in text,
            "detail": "产物必须写明「书里没讲」且不得编造出处",
        },
        "boundary": {
            "passed": "不适用" in text and "边界" in text,
            "detail": "产物必须含不适用条件与能力边界",
        },
        "trigger_hit": {
            "passed": 3 <= len(hits) <= 5,
            "detail": f"description 命中中文触发词 {len(hits)} 个：{hits}",
        },
        "trigger_miss": {
            "passed": not any(w in description for w in _CATCH_ALL),
            "detail": "description 不得含 catch-all 词",
        },
    }
    compliance = validation_report.get("all_passed", False)
    return {
        "schema_version": "1.0",
        "cases": cases,
        "metrics": {
            "negative_refusal_rate": {"value": 1.0 if cases["negative_unanswered"]["passed"] else 0.0,
                                      "metric_type": "measured", "target": 1.00},
            "trigger_hit_rate": {"value": 1.0 if cases["trigger_hit"]["passed"] else 0.0,
                                 "metric_type": "measured", "target": 0.90},
            "artifact_compliance_rate": {"value": 1.0 if compliance else 0.0,
                                         "metric_type": "measured", "target": 1.00},
        },
        "note": "负例任一失败 → S7 abort；本批不含 LLM judge，全部为确定性检查。",
    }
