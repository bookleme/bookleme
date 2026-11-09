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
        engines = list(cfg["fallback"]["engines"])
        genres = [top1, top2]
        source, reason = "ambiguity", cfg["fallback"]["reason"]

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
