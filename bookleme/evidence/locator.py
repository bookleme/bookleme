"""出处的可复核描述：让拿到产物的人能**独立定位**回原文。

Codex 评审的 P1-1：
> 产物给出了 `seg-005 / char_range`，但安装包没有对应的全文和坐标映射，使用者
> 无法靠它独立定位。……内部偏移要说明相对于哪个文件、采用什么编码和范围规则。

现在产物里那行出处是：
    出处：SRC-001 / seg-005 / char_range [12692, 12746) / 可信度 B

读者能知道「在第 5 段」，但不知道：
- `char_range` 相对的是**哪个文件**？（归一化后的全文，不是原始文件）
- 那个文件**在哪**？（cache 路径是运行期产物，安装包里没有）
- 用了什么**编码与归一化**？（所以偏移和原文对不上）
- 怎么**回原文**找这一段？（URL / 标题 / 抓取时间 / 内容哈希）

本模块产出「出处说明块」，把这四件事讲清楚，并给出可复核的最短路径。
"""
from __future__ import annotations

#: 归一化口径（必须与 extract/base.py::normalize 完全一致，否则偏移对不上）
NORMALIZATION_RULE = (
    "仅剥除不可见/控制字符，并折叠康熙部首（U+2F00–U+2FDF）与 "
    "CJK 兼容表意文字（U+F900–U+FAFF）；**不做整篇 NFKC**"
)

#: 范围规则
RANGE_RULE = "左闭右开 [start, end)，按 Python 字符（Unicode 码位）计，非字节"


def build_source_locator(source: dict, segment_heading: str = "",
                         section_path: str = "") -> dict:
    """构造一个可复核的出处定位器。

    `source` 取自 sources.json 的一项：含 source_id / url / sha256 /
    retrieved_at / kind / bytes / tier。
    """
    return {
        "source_id": source.get("source_id", ""),
        "kind": source.get("kind", ""),
        "url": source.get("url", ""),
        "sha256": source.get("sha256", ""),
        "retrieved_at": source.get("retrieved_at", ""),
        "bytes": source.get("bytes", 0),
        "tier": source.get("tier", ""),
        "license_note": source.get("license_note", ""),
        "segment_heading": segment_heading,
        "section_path": section_path,
        "offset_basis": {
            "file": "编译期归一化全文（共享 IR 的 full_text.txt）",
            "encoding": "UTF-8",
            "unit": "Unicode 码位（Python 字符），非字节",
            "range_rule": RANGE_RULE,
            "normalization": NORMALIZATION_RULE,
            "note": ("该文件只存在于编译期缓存（`cache/<book_sha256前12>/full_text.txt`），"
                     "不随产物分发（版权纪律）。要复核请用下方 url + sha256 取回原文，"
                     "自行套用同一归一化规则后按 segment 定位。"),
        },
    }


def render_locator_block(locator: dict, span: dict | None = None) -> str:
    """渲染成产物里的 Markdown 块。"""
    if not locator:
        return ""
    src = locator.get("source_id", "")
    lines = ["", "### 出处复核信息", "",
             "要独立复核这条规则，请按下面四项定位：", ""]

    if locator.get("url"):
        lines.append(f"1. **来源链接**：{locator['url']}")
    else:
        lines.append("1. **来源链接**：本地文件（无 URL）")
    if locator.get("sha256"):
        lines.append(f"2. **内容哈希**（确认拿到的是同一份）：`{locator['sha256']}`")
    if locator.get("retrieved_at"):
        lines.append(f"3. **抓取时间**（材料可能已更新）：{locator['retrieved_at']}")
    else:
        lines.append("3. **抓取时间**：本地文件，无抓取时间")
    if locator.get("segment_heading"):
        lines.append(f"4. **章节标题**：`{locator['segment_heading']}`")
    elif locator.get("section_path"):
        lines.append(f"4. **章节路径**：`{locator['section_path']}`")
    else:
        lines.append("4. **章节标题**：见 `references/coverage.md`")

    if span:
        lines.append(f"   - 本条规则在编译语料中的偏移：`{src}` / "
                     f"{span.get('segment_id', '')} / char_range "
                     f"[{span.get('char_start', 0)}, {span.get('char_end', 0)})")

    basis = locator.get("offset_basis") or {}
    lines += [
        "",
        "**偏移基准**（自己复现时必须用同一套口径，否则字符对不上）：",
        "",
        f"- 相对文件：{basis.get('file', '')}",
        f"- 编码：{basis.get('encoding', '')}",
        f"- 计数单位：{basis.get('unit', '')}",
        f"- 范围规则：{basis.get('range_rule', '')}",
        f"- 归一化：{basis.get('normalization', '')}",
        "",
        f"> {basis.get('note', '')}",
    ]
    if locator.get("license_note"):
        lines.append("")
        lines.append(f"> 授权说明：{locator['license_note']}")
    return "\n".join(lines) + "\n"


def render_project_evidence_block(project: dict | None) -> str:
    """P1-2：区分「原文说了什么」与「本项目验证了什么」。

    Codex 评审的 P1-2：
    > 运行结果按「原文说了什么 → 本项目发现了什么 → 哪些已验证 → 哪些待验证」
    > 组织，并标注项目代码版本、作业和测试范围。

    工程场景的四段式模板：
    - Wiki 的说法：原文在哪，适用于什么版本
    - 当前项目证据：对应代码、配置、作业或日志是什么
    - 验证结果：实际运行了什么，结果是什么
    - 尚待验证：缺哪些数据，什么现象会推翻当前判断
    """
    if not project:
        return ""
    lines = ["", "### 原文案例 vs 本项目验证", "",
             "> **原文说的**是这本书里的做法，**不代表**你的项目也这么做。"
             "下面四段分开，别把前者当后者用。", ""]

    def section(title: str, key: str, fallback: str = "") -> None:
        items = project.get(key) or []
        lines.append(f"**{title}**")
        if not items:
            lines.append(f"- （未提供{fallback}）")
        else:
            for it in items:
                lines.append(f"- {it}")
        lines.append("")

    section("Wiki 的说法（原文在哪、适用于什么版本）", "source_says",
            "原文出处")
    section("当前项目证据（代码 / 配置 / 作业 / 日志）", "project_evidence",
            "项目证据")
    section("验证结果（实际运行了什么）", "verified", "验证结果")
    section("尚待验证（缺什么、什么会推翻当前判断）", "pending",
            "待验证项")
    meta = []
    if project.get("code_version"):
        meta.append(f"- 项目代码版本：`{project['code_version']}`")
    if project.get("job_ids"):
        meta.append(f"- 相关作业：{project['job_ids']}")
    if project.get("test_scope"):
        meta.append(f"- 测试范围：{project['test_scope']}")
    if project.get("data_version"):
        meta.append(f"- 数据版本：`{project['data_version']}`")
    if meta:
        lines += ["**本次验证的上下文**", "", *meta, ""]
    return "\n".join(lines) + "\n"
