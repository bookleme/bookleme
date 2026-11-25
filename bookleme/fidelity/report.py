"""Build claim ledger and the 7 measurable fidelity metrics.

Every metric carries metric_type = measured | heuristic. Heuristic judges
(V2/V3/groundedness) are NOT wired to an LLM in this batch and are reported
as null rather than fabricated numbers.
"""

from __future__ import annotations


def build_claim_ledger(caps: dict, book_sha256: str, evidence_dir: str) -> dict:
    claims = []
    for cap in caps["capabilities"]:
        text = cap["ria"]["I_rephrase"]
        quote_ok = bool(cap["checks"].get("quote_verified"))
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
                "v1_cross_domain": [],
                "v1_type": "measured",
                "v2_predictive_q": "",
                "v2_pass": None,
                "v2_type": "heuristic",
                "v3_uniqueness": None,
                "v3_pass": None,
                "v3_type": "heuristic",
            },
            "groundedness": None,
            "groundedness_type": "heuristic",
            "status": "supported" if quote_ok and cap["status"] == "verified" else "invalidated",
            "evidence_path": evidence_dir,
        })
    return {"schema_version": "1.0", "book_sha256": book_sha256, "claims": claims}


def build_fidelity_report(caps: dict, ledger: dict, segments: dict, quote_records: list[dict],
                          config: dict, artifact_text: str = "") -> dict:
    caps_list = caps["capabilities"]
    claims = ledger["claims"]
    segs = segments["segments"]

    resolved = sum(1 for c in claims if c["source_id"] and c.get("quote_verified"))
    violations = sum(1 for r in quote_records if not r["quote_verified"] or r["ria_errors"])
    verified_segments = {c["span"]["segment_id"] for c in caps_list if c["status"] == "verified"}
    invalidated = sum(1 for c in claims if c["status"] == "invalidated")

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
                invalidated / max(1, len(claims)), "measured+heuristic", 0.05,
                "V1 部分实测；V2/V3 启发式尚未接入"),
            "groundedness": metric(
                None, "heuristic", None, "3 独立 LLM judge 多数投票；本批未接入，只报告不设硬门"),
            "shingle_overlap_max": metric(
                None, "measured", config["shingle_overlap_ceiling"],
                "由 S7 copyright_gate 对产物全文计算后回填"),
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
