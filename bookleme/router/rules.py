"""Weighted genre scoring, hard gates, margin fallback and explicit overrides."""

from __future__ import annotations

from .ambiguity import build_evidence
from .features import FEATURE_NAMES, compute_features, normalize_features


def route(full_text: str, segments: list[dict], toc: list[dict], cfg: dict,
          *, engine_override: str | None = None, genre_override: str | None = None,
          no_router: bool = False) -> tuple[dict, dict | None]:
    features = compute_features(full_text, segments, toc)
    norm = normalize_features(features, cfg)
    scores = {}
    for genre, weights in cfg["weights"].items():
        score = cfg["prior"].get(genre, 0.0) + sum(
            float(weights.get(f, 0.0)) * norm[f] for f in FEATURE_NAMES
        )
        scores[genre] = round(score, 6)

    fired: list[str] = []
    for gate in cfg["hard_gates"]:
        ok = True
        for name, cond in gate["when"].items():
            value = features.get(name, 0.0)
            if "min" in cond and value < cond["min"]:
                ok = False
            if "max" in cond and value > cond["max"]:
                ok = False
        if ok:
            scores[gate["target"]] = round(scores[gate["target"]] + gate["bonus"], 6)
            fired.append(gate["id"])

    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    top1, top2 = ranked[0][0], ranked[1][0]
    margin = round(ranked[0][1] - ranked[1][1], 6)
    threshold = float(cfg["margin_threshold"])
    evidence = None

    if no_router:
        engines, genres, source, reason = (
            ["knowledge_pack", "behavior_skill"], [top1, top2],
            "cli", "no-router: 显式关闭路由，双引擎全出",
        )
    elif margin >= threshold:
        engines = list(cfg["default_engines"][top1])
        genres, source, reason = [top1], "auto", "margin >= threshold"
    else:
        evidence = build_evidence(segments, cfg["ambiguity_sample_size"])
        # 歧义兜底：按 top1 体裁自己的引擎表出产物，而不是无条件双出。
        # 为什么：原兜底固定输出 knowledge_pack + behavior_skill，于是任何
        # margin 偏小的技术文档都会硬套一个「自我对话教练」——它的触发词是
        # 「人生设计/自我对话/迷茫」，与 RL 基础设施这类技术内容完全无关，
        # 实测 microsoft.ai 页面就产出了错配的教练技能。
        # 现在：top1 若本身对应单引擎（knowledge_reference → knowledge_pack），
        # 就只出那一个；top1 对应多引擎体裁时才双出（保留双出能力）。
        default_for_top1 = list(cfg["default_engines"].get(top1) or [])
        if len(default_for_top1) > 1:
            engines = default_for_top1
        else:
            engines = default_for_top1 or list(cfg["fallback"]["engines"])
        # genres 仍保留 top2：它不产引擎，但参与体裁必填字段的选取
        # （pipeline 用 genres[0] 之外的体裁补 genre_fields）。
        genres = [top1, top2] if top2 != top1 else [top1]
        source, reason = "ambiguity", (
            cfg["fallback"]["reason"] +
            f"（按 top1={top1} 的引擎表出产物，不无条件双出）"
        )

    if genre_override:
        genres = [genre_override]
        engines = list(cfg["default_engines"].get(genre_override, cfg["fallback"]["engines"]))
        source, reason = "cli", f"genre override: {genre_override}"

    if engine_override:
        engines = {
            "knowledge_pack": ["knowledge_pack"],
            "behavior_skill": ["behavior_skill"],
            "both": ["knowledge_pack", "behavior_skill"],
            "auto": engines,
        }[engine_override]
        source = "cli"
        reason = f"engine override: {engine_override}"

    result = {
        "schema_version": "1.0",
        "features": {k: round(v, 6) for k, v in features.items()},
        "normalized_features": {k: round(v, 6) for k, v in norm.items()},
        "hard_gates_fired": fired,
        "scores": scores,
        "top1": top1, "top2": top2,
        "margin": margin,
        "confidence": round(min(1.0, margin / max(threshold, 1e-9)), 6),
        "engines": engines,
        "genres": genres,
        "override_source": source,
        "reason": reason,
    }
    return result, evidence
