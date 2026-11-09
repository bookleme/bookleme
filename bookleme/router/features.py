"""12 deterministic routing features. No LLM involvement: two runs must be identical."""

from __future__ import annotations

import re

FEATURE_NAMES = [
    "second_person_ratio", "question_density", "dialogue_marker_ratio",
    "imperative_ratio", "procedure_density", "checklist_marker_ratio",
    "numeric_threshold_density", "evidence_marker_density", "citation_density",
    "named_framework_count", "heading_depth", "toc_imperative_headings",
]

_SENT_SPLIT = re.compile(r"[。！？!?\n]+")
_SECOND_PERSON = re.compile(r"你|您|自己")
_DIALOGUE = re.compile(r"追问|反问|再问|请你回答|自查|问自己|一问一答")
_IMPERATIVE = re.compile(r"^(?:请|先|应当|试着|写下|回答|不要|别|请先|先问)")
_PROCEDURE = re.compile(r"第[一二三四五六七八九十\d]+步|阶段|流程|首先|然后|接着|最后|三张表")
_CHECKLIST = re.compile(r"清单|检查项|逐项|勾选|是否满足|逐项核查")
_NUMERIC = re.compile(r"\d+(?:\.\d+)?\s*(?:倍|%|％|个百分点|阈值|以上|以下|元|倍率|倍)")
_EVIDENCE = re.compile(r"证据|数据来源|验证|证伪|报表|口径|溯源|勾稽")
_CITATION = re.compile(r"\[\d+\]|脚注|参见|出处|第\d+页|来源：")
_NAMED = re.compile(r"《[^》]+》|[A-Z][A-Za-z]+\s*(?:模型|框架|法则|原则|定律)")
_TOC_IMPERATIVE = re.compile(r"^(?:请|如何|为什么|怎样|要不要|该不该)|[？?]$")


def compute_features(text: str, segments: list[dict], toc: list[dict]) -> dict[str, float]:
    sentences = [s.strip() for s in _SENT_SPLIT.split(text) if s.strip()]
    n_sent = max(1, len(sentences))
    chars = max(1, len(text))

    def per_1k(count: int) -> float:
        return count * 1000.0 / chars

    headings = [t.get("heading", "") for t in toc] or [s.get("heading", "") for s in segments]
    toc_imperative = (
        sum(1 for h in headings if _TOC_IMPERATIVE.search(h)) / max(1, len(headings))
    )

    return {
        "second_person_ratio": sum(1 for s in sentences if _SECOND_PERSON.search(s)) / n_sent,
        "question_density": per_1k(text.count("?") + text.count("？")),
        "dialogue_marker_ratio": sum(1 for s in sentences if _DIALOGUE.search(s)) / n_sent,
        "imperative_ratio": sum(1 for s in sentences if _IMPERATIVE.match(s)) / n_sent,
        "procedure_density": per_1k(len(_PROCEDURE.findall(text))),
        "checklist_marker_ratio": sum(1 for s in sentences if _CHECKLIST.search(s)) / n_sent,
        "numeric_threshold_density": per_1k(len(_NUMERIC.findall(text))),
        "evidence_marker_density": per_1k(len(_EVIDENCE.findall(text))),
        "citation_density": per_1k(len(_CITATION.findall(text))),
        "named_framework_count": float(len(_NAMED.findall(text)) + text.count("[CAP]")),
        "heading_depth": float(max([s.get("level", 1) for s in segments] or [1])),
        "toc_imperative_headings": toc_imperative,
    }


def normalize_features(features: dict[str, float], cfg: dict) -> dict[str, float]:
    out = {}
    for name in FEATURE_NAMES:
        cap = float(cfg["features"][name]["cap"])
        out[name] = min(1.0, max(0.0, float(features[name]) / cap)) if cap else 0.0
    return out
