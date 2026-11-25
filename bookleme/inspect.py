"""编译产物检视台（Artifact Inspector）：把一次 run 的产物变成一个能看的页面。

为什么要有它（产品准则「界面自己说明自己」「此刻没用的就不出现」）：
产物原本散在 `out/<run_id>/` 的几个 JSON 和 `build/` 的 Markdown 里，用户要理解
「这次编译到底得到了什么」只能手工翻文件。检视台把**结论**放在最前面：这一版
能不能用、哪几道门过了、图在哪张、哪张卡不可信。

设计约束：
- **单文件、零依赖、离线可开**：CSS/JS/数据全部内联；图片走相对路径引用
  `build/` 里的真实资产（不 base64，避免文件膨胀与重复）。
- **不重复造事实**：所有数字都来自既有 JSON 产物，检视台不重算、不改写口径。
- **图与卡不复制正文**：避免把原文文本再抄一遍（版权纪律），只给图与定位信息。
"""

from __future__ import annotations

import json
import urllib.parse
from pathlib import Path

from .config import CACHE_DIR, OUT_DIR, ROOT, STATE_PATH


def _load(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _rel_url(path: Path, base: Path) -> str:
    """把绝对路径变成相对 inspect.html 的 URL（中文目录名需转义）。"""
    try:
        rel = path.relative_to(base)
    except ValueError:
        rel = Path(path.name)
    return "/".join(urllib.parse.quote(p) for p in rel.parts)


def collect(run_id: str) -> dict:
    """收集一次 run 的全部展示数据（只读，不改动任何产物）。"""
    out_dir = OUT_DIR / run_id
    metrics = _load(out_dir / "metrics.json")
    validation = _load(out_dir / "validation_report.json")
    manifest = _load(out_dir / "build_manifest.json")
    prov = _load(out_dir / "provenance_manifest.json")
    dist = _load(out_dir / "distribution_decision.json")

    book = prov.get("book", {}) or {}
    sha = book.get("sha256", "")
    cache = CACHE_DIR / sha[:12] if sha else None
    caps_obj = _load(cache / "capabilities_verified.json") if cache else {}
    figures_obj = _load(cache / "figures.json") if cache else {}

    # 图资产：按产物目录找实际文件（同一份图可能进了两个引擎的产物）
    fig_by_id = {f["figure_id"]: f for f in figures_obj.get("figures", [])}
    art_figs: dict[str, dict[str, str]] = {}
    for art in manifest.get("artifacts", []):
        skill_dir = Path(art.get("skill_dir", ""))
        found: dict[str, str] = {}
        for fid, f in fig_by_id.items():
            if not f.get("image_file"):
                continue
            src = ROOT / f["image_file"]
            suffix = src.suffix
            cand = skill_dir / "assets" / "figures" / f"{fid}{suffix}"
            if cand.is_file():
                found[fid] = _rel_url(cand, out_dir)
        art_figs[art.get("engine", "")] = found

    figures = []
    for f in figures_obj.get("figures", []):
        fid = f["figure_id"]
        imgs = {e: art_figs.get(e, {}).get(fid, "") for e in art_figs}
        figures.append({
            "id": fid, "kind": f.get("kind"), "page": f.get("page"),
            "source_id": f.get("source_id"),
            "anchored": f.get("char_start") is not None,
            "anchor_kind": f.get("anchor_kind", ""),
            "caption_len": len(f.get("caption", "") or ""),
            "has_image": bool(f.get("image_file")),
            # 图片没随产物落地就别给空路径：页面会显示一个永远转圈的破图
            "image_missing": bool(f.get("image_file")) and not any(imgs.values()),
            "images": imgs,
            "linked_caps": [c["capability_id"] for c in caps_obj.get("capabilities", [])
                            if fid in (c.get("figure_refs") or [])],
        })

    cards = []
    for c in caps_obj.get("capabilities", []):
        ria = c.get("ria", {})
        cards.append({
            "id": c.get("capability_id"), "title": c.get("title"),
            "status": c.get("status"), "tier": (c.get("confidence") or {}).get("tier"),
            "source_id": c.get("source_id"),
            "segment": (c.get("span") or {}).get("segment_id"),
            "trigger": ria.get("A2_user_trigger", ""),
            "rephrase": ria.get("I_rephrase", ""),
            "not_applicable": ria.get("B_not_applicable", ""),
            "steps": ria.get("A3_steps", []),
            "figure_refs": c.get("figure_refs", []),
            "genre_fields": c.get("genre_fields", {}) or {},
            "origin": c.get("origin", "text"),
        })

    gates = []
    for art in validation.get("artifacts", []):
        gate = art.get("copyright_gate", {})
        for chk in gate.get("checks", []):
            gates.append({"engine": art.get("engine"), "name": chk.get("name"),
                          "passed": chk.get("passed"), "value": chk.get("value"),
                          "ceiling": chk.get("ceiling")})

    stages = []
    state = _load(STATE_PATH)
    run_state = ((state.get("runs") or {}).get(run_id) or {})
    for stage in ("S0", "S1", "S2", "S3", "S4", "S5", "S6", "S7", "S8", "S9"):
        info = (run_state.get("stages") or {}).get(stage)
        if info:
            stages.append({"stage": stage,
                           "status": info.get("status", ""),
                           "note": info.get("note", ""),
                           "degraded": info.get("degraded", False),
                           "ts": info.get("ts", "")})

    fidelity = metrics.get("fidelity", {}) or {}
    fidelity_report = _load(cache / "fidelity_report.json") if cache else {}
    judge = fidelity_report.get("judge_summary") or metrics.get("judge_summary") or {}
    assumptions = fidelity_report.get("unverified_assumptions") or metrics.get("unverified_assumptions") or {}
    metrics_rows = []
    for key, val in fidelity.items():
        if isinstance(val, dict):
            metrics_rows.append({
                "key": key, "value": val.get("value"), "type": val.get("metric_type"),
                "target": val.get("target"), "note": val.get("note", ""),
            })

    return {
        "run_id": run_id,
        "title": book.get("title", run_id),
        "author": book.get("author", ""),
        "user_rights": book.get("user_rights", ""),
        "sources": [{"source_id": s.get("source_id"), "origin": s.get("origin"),
                     "kind": s.get("kind"), "tier": s.get("tier"),
                     "url": s.get("url", "")} for s in prov.get("sources", [])],
        "all_passed": validation.get("all_passed"),
        "complete": bool(metrics) and bool(validation),
        "distribution": {"decision": (prov.get("distribution") or {}).get("decision", ""),
                        "reason": (prov.get("distribution") or {}).get("reason", ""),
                        "requested_public": dist.get("requested_public"),
                        "figures_embedded": dist.get("figures_embedded", 0)},
        "extractor": metrics.get("extractor"),
        "llm_calls": metrics.get("llm_calls"),
        "metrics": metrics_rows,
        "judge": judge,
        "assumptions": assumptions,
        "figures_summary": metrics.get("figures", {}) or {},
        "figures": figures,
        "cards": cards,
        "gates": gates,
        "stages": stages,
        "artifacts": [{"engine": a.get("engine"), "genre_id": a.get("genre_id"),
                       "display_name": a.get("display_name"), "slug": a.get("slug"),
                       "file_count": len(a.get("files", [])),
                       "figure_assets": len(a.get("figure_assets", [])),
                       "skill_dir": a.get("skill_dir", "")} for a in manifest.get("artifacts", [])],
    }


TEMPLATE_PATH = Path(__file__).with_name("inspector_template.html")


def render(data: dict) -> str:
    """把展示数据注入模板，产出单文件、可离线打开的 HTML。"""
    tpl = TEMPLATE_PATH.read_text(encoding="utf-8")
    payload = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    # 避免数据里的 </script> 提前闭合脚本块
    payload = payload.replace("</", "<\\/")
    start = "/*__DATA__*/null/*__DATA__*/"
    if start not in tpl:
        raise RuntimeError("检视台模板缺少数据占位符")
    return tpl.replace(start, payload)


def write(run_id: str) -> Path:
    """生成检视台文件，返回其绝对路径。"""
    data = collect(run_id)
    if not (OUT_DIR / run_id).is_dir():
        raise FileNotFoundError(f"找不到 run：{OUT_DIR / run_id}")
    target = OUT_DIR / run_id / "inspect.html"
    target.write_text(render(data), encoding="utf-8")
    return target
