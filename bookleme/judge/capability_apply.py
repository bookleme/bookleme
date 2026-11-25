"""把宿主 Agent 抽取的能力卡回填进 run，并重跑下游阶段。

回填链（与管线 S4→S9 一致）：
1. 宿主填的卡 → blocks → `cache/capabilities.json`（重写）
2. S5：逐字回验引文 → `capabilities_verified.json` + ledger + fidelity
3. S6/S7：重新渲染产物并过版权门
4. S9：重算指标

为什么不只改产物：产物是渲染出来的，改产物会在下次 run 被覆盖。必须改
**共享 IR**（capabilities.json），让渲染层重新生成——这样产物与 IR 一致，
下次重跑也不会回退。

版权约束：宿主填的卡含更长的引文与规则文本，可能触碰「总引文比 ≤3%」硬门。
所以回填后必须重跑版权门；不通过就不该假装成功——如实报告。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..capabilities.extract import extract_capabilities
from ..config import OUT_DIR, load_json
from ..fidelity.judge import v1_cross_domain
from ..fidelity.report import build_claim_ledger, build_fidelity_report
from ..fidelity.quotes import verify_quotes
from .capability import apply_answers, load_answers


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def apply_to_run(run_id: str, answers_path: Path, *, config: dict,
                 root: Path | None = None) -> dict:
    """把宿主 Agent 的抽取结果应用到指定 run，回填能力卡并重算下游。

    返回 {applied, cards, rejected, quote_ratio, ...}。
    """
    from .apply import _cache_dir_from_state

    base = Path(root) if root else OUT_DIR
    run_dir = base / run_id
    metrics_path = run_dir / "metrics.json"
    if not metrics_path.is_file():
        raise FileNotFoundError(f"没有这次 run 的指标文件：{metrics_path}")

    metrics = load_json(metrics_path)
    cache_dir = Path(metrics.get("cache_dir") or _cache_dir_from_state(run_id))
    if not cache_dir.is_dir():
        raise FileNotFoundError(f"找不到 cache 目录：{cache_dir}")

    caps_path = cache_dir / "capabilities.json"
    full_text_path = cache_dir / "full_text.txt"
    segments_path = cache_dir / "segments.json"
    for p in (caps_path, full_text_path, segments_path):
        if not p.is_file():
            raise FileNotFoundError(f"缺少必要文件：{p}")

    full_text = full_text_path.read_text(encoding="utf-8", errors="replace")
    segments = load_json(segments_path)
    old_caps = load_json(caps_path)

    # 体裁额外必填字段（从旧能力卡反查 —— 渲染层已经把它写进卡里了）
    genre_fields: dict = {}
    for cap in old_caps.get("capabilities", []):
        gf = cap.get("genre_fields")
        if isinstance(gf, dict) and gf:
            genre_fields = {k: "" for k in gf}
            break

    answers = load_answers(Path(answers_path))
    blocks, rejected = apply_answers(full_text, segments["segments"], answers,
                                     genre_fields=genre_fields)
    if not blocks:
        return {
            "applied": False,
            "cards": 0,
            "rejected": rejected,
            "reason": "没有一张卡通过契约校验（引文须逐字、规则不得照抄原文）",
        }

    # 重建能力卡（走管线同一个构造函数，保证 schema 一致）
    new_caps = extract_capabilities(full_text, segments["segments"], config,
                                    book_title=metrics.get("book_title", ""),
                                    genre_fields=genre_fields,
                                    host_blocks=blocks)
    _write_json(caps_path, new_caps)

    # 把宿主卡另存一份：管线 S4 下次跑会读它（见 pipeline._load_host_blocks），
    # 这样「宿主承接 → 重跑 → 产物更新」闭环成立，且不会因为清缓存而丢失。
    _write_json(cache_dir / "host_capabilities.json",
                {"schema_version": "1.0", "channel": "host_agent",
                 "blocks": blocks, "rejected": rejected})

    # ---- S5：逐字回验 + 账本 + 忠实度 ----
    char_map_path = cache_dir / "char_map.json"
    char_map = load_json(char_map_path) if char_map_path.is_file() else {}
    cm = char_map.get("map", char_map) if isinstance(char_map, dict) else char_map
    caps_v, quote_records = verify_quotes(
        json.loads(json.dumps(new_caps, ensure_ascii=False)), full_text, cm, config)
    _write_json(cache_dir / "capabilities_verified.json", caps_v)

    judge = metrics.get("judge_summary") or metrics.get("judge")
    judge_result = None
    if judge and judge.get("enabled"):
        # 宿主判过的 judge 结果要一并重算到新卡上（capability_id 顺序可能变，
        # 所以按标题匹配回填）
        judge_result = _remap_judge(old_caps, new_caps, judge)

    v1 = v1_cross_domain(caps_v, segments)
    ledger = build_claim_ledger(caps_v, metrics.get("book_sha256", ""),
                                str(cache_dir / "slices"),
                                judge=judge_result, v1=v1)
    _write_json(cache_dir / "claim_ledger.json", ledger)
    fidelity = build_fidelity_report(caps_v, ledger, segments, quote_records,
                                     config, judge=judge_result)
    _write_json(cache_dir / "fidelity_report.json", fidelity)

    # ---- 指标回填 ----
    old_fidelity = dict(metrics.get("fidelity") or {})
    metrics["fidelity"] = fidelity["metrics"]
    for key in ("negative_refusal_rate", "shingle_overlap_max"):
        if metrics["fidelity"].get(key, {}).get("value") is None:
            prev = old_fidelity.get(key)
            if isinstance(prev, dict) and prev.get("value") is not None:
                metrics["fidelity"][key] = prev
    metrics["extractor"] = new_caps["extractor"]
    metrics["note"] = (
        "能力卡由宿主 Agent 承接抽取（host-agent channel）；"
        "确定性指标（逐字回验/覆盖率/版权门）由 Python 产出。"
    )
    _write_json(metrics_path, metrics)

    return {
        "applied": True,
        "cards": len(new_caps.get("capabilities", [])),
        "rejected": rejected,
        "extractor": new_caps["extractor"],
        "metrics_path": str(metrics_path),
        "capabilities_path": str(caps_path),
    }


def _remap_judge(old_caps: dict, new_caps: dict, judge: dict) -> dict:
    """按**标题**把旧 judge 判定映射到新卡（capability_id 会因重排而变）。"""
    results = judge.get("results") or {}
    old_by_title = {}
    for cap in old_caps.get("capabilities", []):
        jr = results.get(cap.get("capability_id"))
        if jr:
            old_by_title[cap.get("title", "")] = jr
    new_results = {}
    for cap in new_caps.get("capabilities", []):
        jr = old_by_title.get(cap.get("title", ""))
        if jr:
            new_results[cap.get("capability_id", "")] = jr
    out = dict(judge)
    out["results"] = new_results
    s = out.get("summary") or {}
    judged = [r for r in new_results.values() if r.get("judged")]
    s = dict(s)
    s["capabilities"] = len(new_results)
    s["judged"] = len(judged)
    s["grounded"] = sum(1 for r in judged if r.get("grounded") is True)
    s["grounded_unknown"] = sum(1 for r in judged if r.get("grounded") is None)
    s["v2_pass"] = sum(1 for r in judged if r.get("v2_pass") is True)
    s["v3_pass"] = sum(1 for r in judged if r.get("v3_pass") is True)
    out["summary"] = s
    return out
