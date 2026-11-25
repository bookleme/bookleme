"""产物可用性验收：这次编出来的技能，到底能不能用、哪里薄。

这不是格式校验（那是 `validate`），也不是指标罗列（那是 `eval`）。
它回答用户真正关心的三个问题：

1. **能回答什么** —— 有哪些已验证框架、各自对应什么提问；
2. **能不能照着做** —— 每张卡有没有可执行步骤、边界、可逐字定位的出处；
3. **哪里薄** —— 哪些图没锚定、哪些卡缺边界、索引有没有指向不存在的文件。

三条原则都落在这里：结论先给（第一行就是判决）；不确定就明说（缺失计入
「薄弱」而不是假装通过）；数字必须可复算（只读既有产物，不重新推断）。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .config import OUT_DIR, load_json

FRAMEWORK_RE = re.compile(r"framework-(\d+)\.md$")
INDEX_ROW_RE = re.compile(r"\|\s*`(references/[^`]+\.md)`\s*\|\s*$", re.M)
STEP_RE = re.compile(r"^\s*\d+\.\s+\S", re.M)


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


def _resolution_dir(artifact: dict, run_dir: Path) -> Path | None:
    """manifest 里存的是绝对路径；产物被搬走后要能从 run 目录重新找到。"""
    raw = artifact.get("skill_dir") or ""
    if raw and Path(raw).is_dir():
        return Path(raw)
    # 退化路径：build/<engine>/<display_name（slug）>
    guess = run_dir / "build" / str(artifact.get("engine", "")) / f"{artifact.get('display_name', '')}（{artifact.get('slug', '')}）"
    if guess.is_dir():
        return guess
    # 最后按 slug 在 build 下模糊找一次（目录名可能被改过）
    slug = artifact.get("slug") or ""
    if slug and (run_dir / "build").is_dir():
        for d in (run_dir / "build").rglob("*"):
            if d.is_dir() and slug in d.name:
                return d
    return None


def _check_artifact(artifact: dict, run_dir: Path) -> dict:
    skill_dir = _resolution_dir(artifact, run_dir)
    result = {
        "engine": artifact.get("engine", ""),
        "name": artifact.get("display_name", ""),
        "slug": artifact.get("slug", ""),
        "resolved_dir": str(skill_dir or ""),
        "found": bool(skill_dir),
        "frameworks": 0,
        "actionable": 0,      # 有 >=2 步且写了边界
        "traceable": 0,       # 有 SRC 出处与 char_range
        "index_rows": 0,
        "index_broken": [],   # 指向不存在文件的索引行
        "index_duplicate": [],  # 指向同一文件的多行（路由会失效）
        "hard": [],
        "soft": [],
        "can_answer": [],
        "cannot_answer": [],
    }
    if not skill_dir:
        result["hard"].append("产物目录找不到（manifest 里的路径失效，也没能在 build/ 下定位）")
        return result

    skill_md = _read(skill_dir / "SKILL.md")
    if not skill_md:
        result["hard"].append("SKILL.md 缺失或为空")
        return result
    for section in ("## 核心定位", "## 触发场景", "## 工作流", "## 输出格式", "## Gotchas"):
        if section not in skill_md:
            result["hard"].append(f"SKILL.md 缺章节 {section}")
    if "书里没讲" not in skill_md:
        result["hard"].append("SKILL.md 未写明「书里没讲」的拒答规则（会诱导编造）")

    refs = skill_dir / "references"
    shards = sorted(p for p in refs.glob("framework-*.md")) if refs.is_dir() else []
    result["frameworks"] = len(shards)
    if not shards:
        result["hard"].append("没有任何框架分片：这个技能没有可执行内容")

    for shard in shards:
        text = _read(shard)
        if "何时读本文件" not in text:
            result["soft"].append(f"{shard.name} 缺「何时读本文件」")
        has_steps = len(STEP_RE.findall(text)) >= 2
        has_boundary = ("不适用" in text) or ("边界" in text)
        has_source = ("SRC-" in text) and ("char_range" in text)
        if has_steps and has_boundary:
            result["actionable"] += 1
        else:
            missing = "、".join(x for x, ok in (("执行步骤", has_steps), ("边界", has_boundary)) if not ok)
            result["soft"].append(f"{shard.name} 缺{missing}")
        if has_source:
            result["traceable"] += 1
        else:
            result["hard"].append(f"{shard.name} 没有可逐字定位的出处（SRC + char_range）")
        # 「能回答什么」：取分片标题当能力名
        title = ""
        for line in text.splitlines():
            if line.startswith("## 框架："):
                title = line[len("## 框架："):].strip()
                break
        if title:
            result["can_answer"].append(title)

    index_text = _read(refs / "topic-index.md")
    if index_text:
        targets = INDEX_ROW_RE.findall(index_text)
        result["index_rows"] = len(targets)
        seen: dict[str, int] = {}
        for t in targets:
            if not (skill_dir / t).is_file():
                result["index_broken"].append(t)
            seen[t] = seen.get(t, 0) + 1
        result["index_duplicate"] = [t for t, n in seen.items() if n > 1]
        if shards and len(targets) < len(shards):
            result["soft"].append(f"索引只列了 {len(targets)} 行，但有 {len(shards)} 个框架分片（有分片路由不到）")
    else:
        result["soft"].append("缺少 references/topic-index.md：智能体无法按需加载，只能全读")

    if result["index_broken"]:
        result["hard"].append("索引指向不存在的文件：" + "、".join(result["index_broken"][:3]))
    if result["index_duplicate"]:
        result["soft"].append("索引有多行指向同一文件：" + "、".join(result["index_duplicate"][:3]))

    smoke_md = _read(skill_dir / "evals" / "smoke.md")
    if not smoke_md:
        result["soft"].append("缺少 evals/smoke.md：没有自测用例，改完无从回归")
    else:
        for kind in ("negative", "boundary", "positive"):
            if kind not in smoke_md:
                result["soft"].append(f"smoke 用例缺 {kind} 类型")

    # 「不能答什么」只从产物里已写明的内容取，不臆测
    result["cannot_answer"].append("书中未涉及的问题（技能会明确回答「书里没讲」）")
    if "专业" in skill_md:
        result["cannot_answer"].append("需要专业资质判断的心理 / 医疗 / 法律 / 投资问题")
    return result


def check_run(run_id: str) -> dict:
    run_dir = OUT_DIR / run_id
    manifest_path = run_dir / "build_manifest.json"
    if not manifest_path.is_file():
        raise FileNotFoundError(f"没有这次 run 的产物清单：{manifest_path}")
    manifest = load_json(manifest_path)
    artifacts = [_check_artifact(a, run_dir) for a in manifest.get("artifacts", [])]

    metrics = {}
    mpath = run_dir / "metrics.json"
    if mpath.is_file():
        metrics = load_json(mpath)
    figs = metrics.get("figures") or {}

    hard = [f"{a['name']}：{msg}" for a in artifacts for msg in a["hard"]]
    soft = [f"{a['name']}：{msg}" for a in artifacts for msg in a["soft"]]
    if figs.get("total"):
        if figs.get("anchored", 0) < figs.get("total", 0):
            soft.append(f"图示：{figs['total'] - figs.get('anchored', 0)} 张未锚定到正文（索引里标「未锚定」）")
        if figs.get("caption_only"):
            soft.append(f"图示：{figs['caption_only']} 张只有图注、没有位图（矢量图无法提取）")

    verdict = "unusable" if hard else ("usable_with_notes" if soft else "usable")
    return {
        "run_id": run_id,
        "verdict": verdict,
        "artifacts": artifacts,
        "hard": hard,
        "soft": soft,
        "metrics": {
            "extractor": metrics.get("extractor", ""),
            "llm_calls": metrics.get("llm_calls", 0),
            "figures": figs,
        },
    }


def format_report(report: dict) -> str:
    """人话版：先判决，再说能干什么，最后说哪里薄。"""
    label = {"usable": "可直接用", "usable_with_notes": "能用，有需要留意的地方",
             "unusable": "不建议用（先修下面的硬问题）"}[report["verdict"]]
    out = [f"run {report['run_id']} · {label}",
           f"抽取方式 {report['metrics'].get('extractor') or '—'}"
           f" · LLM 调用 {report['metrics'].get('llm_calls', 0)} 次", ""]

    for a in report["artifacts"]:
        out.append(f"[{a['engine']}] {a['name']}")
        if not a["found"]:
            out.append("  产物目录没找到，无法验收。")
            out.append("")
            continue
        out.append(f"  框架：{a['frameworks']} 个"
                   f" · 可照着做 {a['actionable']}/{a['frameworks']}"
                   f" · 出处可逐字定位 {a['traceable']}/{a['frameworks']}")
        if a["can_answer"]:
            shown = " / ".join(a["can_answer"][:6])
            more = f" 等，共 {len(a['can_answer'])} 个" if len(a["can_answer"]) > 6 else ""
            out.append(f"  能回答：{shown}{more}")
        out.append(f"  不能答：{'；'.join(a['cannot_answer'])}")
        if a["hard"]:
            out.append("  硬问题：")
            out += [f"    - {m}" for m in a["hard"]]
        if a["soft"]:
            out.append("  可改进：")
            out += [f"    - {m}" for m in a["soft"]]
        out.append("")

    figs = report["metrics"].get("figures") or {}
    if figs.get("total"):
        out.append(f"图示：{figs['total']} 张 · 带位图 {figs.get('with_images', 0)}"
                   f" · 已锚定 {figs.get('anchored', 0)}")
        out.append("")
    if report["hard"]:
        out.append("要修才能用：")
        out += [f"  - {m}" for m in report["hard"]]
        out.append("")
    if report["soft"]:
        out.append("不阻塞使用，但会让技能变薄：")
        out += [f"  - {m}" for m in report["soft"]]
        out.append("")
    out.append("下一步：装到技能目录用 `bookleme run ... --install`；"
               "想直接试，按 SKILL.md 的「触发场景」提问即可。")
    return "\n".join(out)
