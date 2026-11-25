"""Build claim ledger and the 7 measurable fidelity metrics.

Every metric carries metric_type = measured | heuristic. The heuristic judges
(groundedness / V2 / V3) are LLM-judged: they stay `heuristic` by nature (they
depend on a model's subjective scoring) but their VALUES are real when an LLM
judge actually ran — see `fidelity/judge.py`. Without a configured LLM the
values stay null rather than being fabricated.
"""

from __future__ import annotations


def build_claim_ledger(caps: dict, book_sha256: str, evidence_dir: str,
                       judge: dict | None = None,
                       v1: dict | None = None) -> dict:
    judge_results = (judge or {}).get("results", {})
    claims = []
    for cap in caps["capabilities"]:
        text = cap["ria"]["I_rephrase"]
        quote_ok = bool(cap["checks"].get("quote_verified"))
        cid = cap["capability_id"]
        jr = judge_results.get(cid, {})
        grounded = jr.get("grounded")
        claims.append({
            "claim_id": cap["claims"][0] if cap.get("claims") else f"CLM-{cap['capability_id']}",
            "text": text,
            "capability_id": cap["capability_id"],
            "source_id": cap["source_id"],
            "origin": "local",
            "chapter": cap["span"].get("chapter", ""),
            "section": cap["span"].get("section", ""),
            "page": cap["span"].get("page", 0),
            "source_tier": cap["confidence"].get("tier", "C"),
            "quote_char_count": len(cap["ria"]["R_quote"]),
            "quote_verified": quote_ok,
            "verification": {
                "v1_cross_domain": (v1 or {}).get(cid, []),
                "v1_type": "measured",
                "v2_predictive_q": jr.get("v2_question", ""),
                "v2_answer": jr.get("v2_answer", ""),
                "v2_pass": jr.get("v2_pass"),
                "v2_type": "heuristic",
                "v3_uniqueness": jr.get("v3_pass"),
                "v3_pass": jr.get("v3_pass"),
                "v3_type": "heuristic",
                "denylist_hits": jr.get("denylist_hits", []),
                "judge_support": jr.get("support", ""),
                "v3_reason": jr.get("v3_reason", ""),
            },
            "groundedness": (1.0 if grounded is True else (0.0 if grounded is False else None)),
            "groundedness_type": "heuristic",
            "status": "supported" if quote_ok and cap["status"] == "verified" else "invalidated",
            "evidence_path": evidence_dir,
        })
    return {"schema_version": "1.0", "book_sha256": book_sha256, "claims": claims}


def build_fidelity_report(caps: dict, ledger: dict, segments: dict, quote_records: list[dict],
                          config: dict, artifact_text: str = "",
                          judge: dict | None = None) -> dict:
    caps_list = caps["capabilities"]
    claims = ledger["claims"]
    segs = segments["segments"]

    resolved = sum(1 for c in claims if c["source_id"] and c.get("quote_verified"))
    violations = sum(1 for r in quote_records if not r["quote_verified"] or r["ria_errors"])
    verified_segments = {c["span"]["segment_id"] for c in caps_list if c["status"] == "verified"}
    invalidated = sum(1 for c in claims if c["status"] == "invalidated")

    judge = judge or {}
    jsum = judge.get("summary") or {}
    judged_n = int(jsum.get("judged") or 0)
    grounded_n = int(jsum.get("grounded") or 0)
    grounded_unknown = int(jsum.get("grounded_unknown") or 0)
    v2_n = int(jsum.get("v2_pass") or 0)
    v3_n = int(jsum.get("v3_pass") or 0)

    if judge.get("enabled") and judged_n:
        # 有 judge 结果：unsupported = 被判为「不被原文支持」的断言占比
        unsupported = grounded_n
        unsupported_rate = (judged_n - unsupported - grounded_unknown) / max(1, judged_n)
        grounded_value = grounded_n / max(1, judged_n)
        unsupported_note = (f"V1 逐字校验 + LLM judge（model_fingerprint={judge.get('model_fingerprint')}，"
                            f"{judge.get('votes')} 票多数）；judged={judged_n}，"
                            f"未判定={grounded_unknown}（不计为不支持）")
        grounded_note = (f"LLM judge 多数投票（{judge.get('votes')} 个角色），"
                         f"model_fingerprint={judge.get('model_fingerprint')}；"
                         "依赖模型主观判断，故 metric_type 恒为 heuristic")
    else:
        unsupported_rate = invalidated / max(1, len(claims))
        grounded_value = None
        unsupported_note = "V1 部分实测；V2/V3 启发式尚未接入"
        grounded_note = "未接入 LLM judge（无 BOOKLEME_LLM_* 配置），值保持 null，不伪造"

    def metric(value, mtype, target, note=""):
        return {"value": value, "metric_type": mtype, "target": target, "note": note}

    return {
        "schema_version": "1.0",
        "extractor": caps["extractor"],
        "metrics": {
            "citation_resolution_rate": metric(
                resolved / max(1, len(claims)), "measured", 1.00,
                "可解析到 source_id + char_range 的断言占比"),
            "verbatim_violation_rate": metric(
                violations / max(1, len(quote_records)), "measured", 0.00,
                "逐字校验失败或 RIA 六段不全的引文占比"),
            "coverage_score": metric(
                len(verified_segments) / max(1, len(segs)), "measured", 0.85,
                "含 >=1 个 verified capability 的 segment 占比"),
            "negative_refusal_rate": metric(
                None, "measured", 1.00, "由 S9 冒烟测试填充；本阶段不预填"),
            "unsupported_claim_rate": metric(
                unsupported_rate, "measured+heuristic", 0.05, unsupported_note),
            "groundedness": metric(
                grounded_value, "heuristic", None, grounded_note),
            "shingle_overlap_max": metric(
                None, "measured", config["shingle_overlap_ceiling"],
                "由 S7 copyright_gate 对产物全文计算后回填"),
        },
        "judge_summary": {
            "enabled": bool(judge.get("enabled")),
            "model_fingerprint": judge.get("model_fingerprint", ""),
            "prompt_version": judge.get("prompt_version", ""),
            "votes": judge.get("votes", 0),
            "capabilities": jsum.get("capabilities", 0),
            "judged": judged_n,
            "grounded": grounded_n,
            "grounded_unknown": grounded_unknown,
            "v2_pass": v2_n,
            "v2_pass_rate": (v2_n / judged_n) if judged_n else None,
            "v3_pass": v3_n,
            "v3_pass_rate": (v3_n / judged_n) if judged_n else None,
            "denylist_flagged": jsum.get("denylist_flagged", 0),
            "failed_calls": jsum.get("failed_calls", 0),
            "note": ("judge 结论依赖模型主观判断 → V2/V3/groundedness 一律标 heuristic；"
                     "未判定（调用失败）不计为不通过"),
        },
        "quote_records": quote_records,
        "unverified_assumptions": {
            "PD-04": "BLOCKED — 上游研究计划中未实现",
            "PD-05": "UNVERIFIED — 结构化框架是否优于摘要，未经本项目验证（单列，不等于 BLOCKED）",
            "PD-06_TO_PD-12": "BLOCKED — 上游研究计划中全部未实现",
            "upstream_24x_51x": "上游 context-dump 对比自测数据，不得转写成本项目结论",
            "upstream_2.4x_15.6x": "上游 discovery-loop 模型估算（discovery_tax.py 自述），非实测",
            "paper_2x_token_claim": "论文/研究计划中的约 2× token 主张仍处 BLOCKED 假设阶段，不得引用为既成事实",
            "upstream_1dollar_per_book": "上游文档约 $1/书 的 LLM 成本估算（其自述），非本项目实测",
        },
    }
