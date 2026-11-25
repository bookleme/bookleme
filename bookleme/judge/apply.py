"""把宿主 Agent 的 judge 判定回填到 run 的指标产物里。

回填要重算三处（顺序与管线 S5/S9 一致）：
1. `cache/claim_ledger.json` —— 断言账本带上 groundedness / V2 / V3 判定
2. `cache/fidelity_report.json` —— 7 个忠实度指标（groundedness 由 null 变真值）
3. `out/<run_id>/metrics.json` —— 对外汇总

回填**不重跑编译**：能力卡（capabilities_verified.json）与引文逐字校验结果
原样复用——宿主 Agent 只补主观判定，确定性那半不重复算。
"""

from __future__ import annotations

import json
from pathlib import Path

from ..config import OUT_DIR, load_json
from ..fidelity.report import build_claim_ledger, build_fidelity_report
from ..fidelity.judge import v1_cross_domain
from . import apply_answers


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def _cache_dir_from_state(run_id: str) -> str:
    """从 state.json 的 S5 产物路径反推 cache 目录。

    metrics.json 不带 cache_dir（那是给用户看的汇总），但 state.json 里记着
    每个 stage 的产物绝对路径——S5 的第一个产物就是 capabilities_verified.json。
    """
    from ..config import STATE_PATH
    if not STATE_PATH.is_file():
        return ""
    try:
        state = load_json(STATE_PATH)
    except (OSError, ValueError):
        return ""
    runs = state.get("runs") or {}
    run = runs.get(run_id) or {}
    stages = run.get("stages") or {}
    for stage in ("S5", "S4", "S2"):
        outs = (stages.get(stage) or {}).get("outputs") or []
        for out in outs:
            p = Path(out)
            if p.name == "capabilities_verified.json":
                return str(p.parent)
    return ""


def apply_to_run(run_id: str, answers_path: Path, *, config: dict,
                 root: Path | None = None) -> dict:
    """把宿主 Agent 的 answers 应用到指定 run，回填指标。

    返回 {applied, judged, grounded, metrics_path, ...}。
    找不到 run 的产物时抛 FileNotFoundError（明确报错，不静默跳过）。
    """
    from . import load_answers

    base = Path(root) if root else OUT_DIR
    run_dir = base / run_id
    if not run_dir.is_dir():
        raise FileNotFoundError(f"没有这次 run 的产物目录：{run_dir}")

    metrics_path = run_dir / "metrics.json"
    if not metrics_path.is_file():
        raise FileNotFoundError(f"没有这次 run 的指标文件：{metrics_path}")

    metrics = load_json(metrics_path)
    book_sha256 = metrics.get("book_sha256") or ""

    cache_dir = metrics.get("cache_dir") or _cache_dir_from_state(run_id)
    if not cache_dir:
        raise FileNotFoundError(
            f"无法定位 cache 目录（metrics.json 无 cache_dir，state.json 也没有 S5 产物路径）："
            f"{metrics_path}")
    cache_dir = Path(cache_dir)

    caps_path = Path(cache_dir) / "capabilities_verified.json"
    if not caps_path.is_file():
        raise FileNotFoundError(f"没有能力卡文件：{caps_path}")
    caps = load_json(caps_path)

    # 全文语料用于取引文上下文（judge 的判据）
    full_text_path = Path(cache_dir) / "full_text.txt"
    if not full_text_path.is_file():
        # 有些 run 的语料在 out 下
        alt = run_dir / "full_text.txt"
        if alt.is_file():
            full_text_path = alt
        else:
            raise FileNotFoundError(f"没有语料文件，无法提供 judge 上下文：{full_text_path}")
    full_text = full_text_path.read_text(encoding="utf-8", errors="replace")

    segments_path = Path(cache_dir) / "segments.json"
    segments = load_json(segments_path) if segments_path.is_file() else {"segments": []}

    answers = load_answers(Path(answers_path))
    judge_result = apply_answers(caps, answers, config)

    # 重算 ledger 与 fidelity（复用管线同一批函数，口径一致）
    v1 = v1_cross_domain(caps, segments)
    ledger = build_claim_ledger(caps, book_sha256, str(Path(cache_dir) / "slices"),
                                judge=judge_result, v1=v1)
    fidelity = build_fidelity_report(caps, ledger, segments,
                                     ledger.get("quote_records", []) or [],
                                     config, judge=judge_result)
    # quote_records 从原 ledger 取（S5 写入时带的）
    old_ledger_path = Path(cache_dir) / "claim_ledger.json"
    if old_ledger_path.is_file():
        old_ledger = load_json(old_ledger_path)
        qr = old_ledger.get("quote_records")
        if qr:
            fidelity = build_fidelity_report(caps, ledger, segments, qr,
                                             config, judge=judge_result)

    _write_json(old_ledger_path, ledger)
    _write_json(Path(cache_dir) / "fidelity_report.json", fidelity)

    # 回填 metrics.json
    # 先留住原值：negative_refusal_rate / shingle_overlap_max 由 S9 用冒烟结果
    # 与版权门回填，回填重算 fidelity 会把它们变成 null —— 必须在覆盖**之前**
    # 抓住，否则这两个已测得的指标被抹掉。
    old_fidelity = dict(metrics.get("fidelity") or {})
    metrics["fidelity"] = fidelity["metrics"]
    for key in ("negative_refusal_rate", "shingle_overlap_max"):
        if key in metrics["fidelity"] and metrics["fidelity"][key].get("value") is None:
            prev = old_fidelity.get(key)
            if isinstance(prev, dict) and prev.get("value") is not None:
                metrics["fidelity"][key] = prev

    judge_summary = {
        "enabled": True,
        "channel": judge_result["channel"],
        "model_fingerprint": judge_result["model_fingerprint"],
        "votes": judge_result["votes"],
        "judged": judge_result["summary"]["judged"],
        "grounded": judge_result["summary"]["grounded"],
        "grounded_unknown": judge_result["summary"]["grounded_unknown"],
        "v2_pass": judge_result["summary"]["v2_pass"],
        "v3_pass": judge_result["summary"]["v3_pass"],
        "failed_calls": judge_result["summary"]["failed_calls"],
        "summary": judge_result["summary"],
        "answers_path": str(Path(answers_path).resolve()),
    }
    # 两个字段都写：judge_summary 是 eval 读的那个；judge 是完整留痕。
    metrics["judge_summary"] = judge_summary
    metrics["judge"] = judge_summary
    # llm_calls 不变（宿主承接不是 API 调用），但要注明判定来源
    metrics["note"] = (
        "groundedness / V2 / V3 由宿主 Agent 承接判定（host-agent channel，"
        "非外部模型 API 调用）；确定性指标（逐字回验/覆盖率/版权门）由 Python 产出。"
    )
    _write_json(metrics_path, metrics)

    s = judge_result["summary"]
    return {
        "run_id": run_id,
        "applied": True,
        "capabilities": s["capabilities"],
        "judged": s["judged"],
        "grounded": s["grounded"],
        "grounded_unknown": s["grounded_unknown"],
        "v2_pass": s["v2_pass"],
        "v3_pass": s["v3_pass"],
        "channel": judge_result["channel"],
        "metrics_path": str(metrics_path),
        "fidelity_path": str(Path(cache_dir) / "fidelity_report.json"),
    }
