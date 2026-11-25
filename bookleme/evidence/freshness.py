"""源材料新鲜度检查（P2）：源页面变了，提示重新核对并展示差异。

Codex 评审的 P2：
> 团队 Wiki 和代码会更新，生成 skill 时的描述可能很快落后于实际实现。
> 保存 Wiki 页面版本、更新时间和内容摘要或哈希。源页面变化后提示重新核对
> 相关分片，并展示新旧差异。

要解决的实际问题
----------------
产物里写着「Rocket 在 checkpoint 后调整 learner 规模」——这是**编译当天**的
微软做法。三个月后微软改了，或者你的团队 Wiki 更新了，这张卡就过时了，
但产物里没有任何东西提示你「它可能过期了」。

本模块做两件事
--------------
1. **新鲜度判定**：拿记录在案的 sha256 / retrieved_at 对比当前源，判断
   「未变 / 已变 / 未知」。
2. **差异摘要**：变了就给出**哪些分片受影响** + 新旧文本差异（行级），
   让人能快速判断要不要重新编译。

差异用标准库 `difflib`，零依赖。
"""
from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path

#: 新鲜度状态
FRESH = "fresh"          # 与记录一致
CHANGED = "changed"      # 哈希不同 → 源变了
UNKNOWN = "unknown"      # 拿不到当前源（本地文件、离线）
MISSING = "missing"      # 记录里的文件已不存在

#: 判定「内容摘要」用的哈希算法
_HASH_ALGO = "sha256"


def content_digest(data: bytes) -> str:
    return hashlib.new(_HASH_ALGO, data).hexdigest()


def check_freshness(source: dict, current_path: Path | None = None,
                    baseline: dict | None = None) -> dict:
    """判定单个源的新鲜度。

    `source` 取自 sources.json 的一项（含 sha256 / retrieved_at / url /
    path / bytes）；`current_path` 指向当前磁盘上的同一份材料（可选）；
    `baseline` 是「编译时」记录的哈希（来自源快照）。

    **为什么要有 baseline**：sources.json 里记的 sha256 是**本次 run 抓取时**
    写下的，等于「当前」，拿它比自己永远是「未变」——看不出 Wiki 有没有更新。
    真正的比对基准是编译时的快照。
    """
    bl = baseline or {}
    recorded_hash = bl.get("sha256") or source.get("sha256") or ""
    result = {
        "source_id": source.get("source_id", ""),
        "url": source.get("url", ""),
        "recorded_sha256": recorded_hash,
        "recorded_retrieved_at": bl.get("retrieved_at") or source.get("retrieved_at", ""),
        "recorded_bytes": bl.get("bytes") or source.get("bytes", 0),
        "status": UNKNOWN,
        "current_sha256": "",
        "detail": "",
    }

    if not current_path:
        result["detail"] = "未提供当前材料路径，无法比对"
        return result
    p = Path(current_path)
    if not p.is_file():
        result["status"] = MISSING
        result["detail"] = f"记录中的材料已不存在：{p}"
        return result
    data = p.read_bytes()
    cur_hash = content_digest(data)
    result["current_sha256"] = cur_hash
    if not recorded_hash:
        result["status"] = UNKNOWN
        result["detail"] = "记录中没有哈希，无法比对"
    elif cur_hash == recorded_hash:
        result["status"] = FRESH
        result["detail"] = "与编译时一致"
    else:
        result["status"] = CHANGED
        result["detail"] = (f"内容已变：{recorded_hash[:12]} → {cur_hash[:12]}"
                            f"（{source.get('bytes', 0)} → {len(data)} 字节）")
    return result


def diff_text(old_text: str, new_text: str, context: int = 1,
              max_lines: int = 60) -> list[str]:
    """行级差异（unified diff 风格）。"""
    old_lines = (old_text or "").splitlines()
    new_lines = (new_text or "").splitlines()
    diff = list(difflib.unified_diff(old_lines, new_lines,
                                     fromfile="编译时", tofile="当前",
                                     lineterm="", n=context))
    if len(diff) > max_lines:
        diff = diff[:max_lines] + [f"…（差异共 {len(diff)} 行，此处截断）"]
    return diff


def affected_sections(old_text: str, new_text: str, segments: list[dict] | None = None,
                      ) -> list[str]:
    """粗判哪些章节受变化影响。

    `segments` 取 segments.json 的段列表（含 char_range / heading）——
    **用 char_range 直接定位，不用标题字符串搜索**。
    理由：原文里标题带 Markdown 标记（`## Controlling staleness`），
    而 segments 里存的是纯标题（`Controlling staleness`），用 find 搜不到
    正确位置，会误判到别的章节（实测把 staleness 的改动判成 Numerical parity）。

    判据：某个 segment 的 char_range 窗口内出现差异行 → 该段受影响。
    """
    if not old_text or not new_text or not segments:
        return []
    old_lines = old_text.splitlines()
    new_lines = new_text.splitlines()
    sm = difflib.SequenceMatcher(None, old_lines, new_lines)
    changed_old_idx: list[int] = []
    for tag, i1, i2, j1, j2 in sm.get_opcodes():
        if tag != "equal":
            changed_old_idx.extend(range(i1, i2))
    if not changed_old_idx:
        return []
    # 旧文本里每行的起始偏移
    offsets: list[int] = []
    pos = 0
    for line in old_lines:
        offsets.append(pos)
        pos += len(line) + 1
    changed_offsets = [offsets[i] for i in changed_old_idx if i < len(offsets)]

    affected: list[str] = []
    for seg in segments:
        rng = seg.get("char_range") or []
        if len(rng) != 2:
            continue
        lo, hi = int(rng[0]), int(rng[1])
        heading = str(seg.get("heading", "")).strip()
        if not heading:
            continue
        for off in changed_offsets:
            if lo <= off < hi:
                affected.append(f"{seg.get('segment_id', '')} {heading}")
                break
    return affected


def build_freshness_report(sources: list[dict], current_paths: dict | None = None,
                            segment_headings: list[str] | None = None,
                            baseline: dict | None = None) -> dict:
    """构造新鲜度报告。

    `current_paths`：source_id → 当前材料路径（用于比对）。
    `baseline`：source_id → 编译时快照的哈希（比对基准）。
    """
    current_paths = current_paths or {}
    baseline = baseline or {}
    checks = []
    for src in sources:
        sid = src.get("source_id", "")
        cp = current_paths.get(sid)
        if cp is None and src.get("path"):
            cp = Path(src["path"])
        checks.append(check_freshness(src, cp, baseline.get(sid)))
    changed = [c for c in checks if c["status"] == CHANGED]
    return {
        "schema_version": "1.0",
        "kind": "source_freshness_report",
        "checks": checks,
        "summary": {
            "total": len(checks),
            "fresh": sum(1 for c in checks if c["status"] == FRESH),
            "changed": len(changed),
            "unknown": sum(1 for c in checks if c["status"] == UNKNOWN),
            "missing": sum(1 for c in checks if c["status"] == MISSING),
        },
        "note": ("源材料变了 → 受影响的分片需重新核对。"
                 "重跑 `bookleme run` 会用新内容重编译；"
                 "若只想看差异，用 `bookleme freshness` 导出报告。"),
    }


def render_freshness_md(report: dict, diffs: dict | None = None) -> str:
    """渲染成产物里的 Markdown。"""
    s = report.get("summary") or {}
    lines = ["# 源材料新鲜度", "",
             report.get("note", ""), "",
             "| 源 | 抓取时间 | 状态 | 说明 |", "| --- | --- | --- | --- |"]
    labels = {FRESH: "未变", CHANGED: "**已变**", UNKNOWN: "未知", MISSING: "已丢失"}
    for c in report.get("checks", []):
        lines.append(f"| `{c['source_id']}` | {c.get('recorded_retrieved_at') or '—'} "
                     f"| {labels.get(c['status'], c['status'])} | {c.get('detail', '')} |")
    lines += ["", f"合计 {s.get('total', 0)} 个源："
                  f"未变 {s.get('fresh', 0)} · 已变 {s.get('changed', 0)} · "
                  f"未知 {s.get('unknown', 0)} · 已丢失 {s.get('missing', 0)}", ""]
    if diffs:
        lines += ["## 新旧差异", ""]
        for name, diff in diffs.items():
            lines += [f"### {name}", "", "```diff"]
            lines += diff or ["（无差异）"]
            lines += ["```", ""]
    return "\n".join(lines) + "\n"


def save_report(report: dict, path: Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
