"""Local skill-creator 13-item self-check (the official validator does NOT do these)."""

from __future__ import annotations

import re
from pathlib import Path

SECTIONS = ["## 核心定位", "## 触发场景", "## 工作流", "## 输出格式", "## Gotchas"]
FORBIDDEN_FILES = {"README.md", "CHANGELOG.md", "INSTALL.md", "full_text.txt"}


def lint_skill_dir(skill_dir: Path, max_lines: int = 500) -> list[str]:
    skill_dir = Path(skill_dir)
    errors: list[str] = []
    skill_md = skill_dir / "SKILL.md"
    if not skill_md.exists():
        return ["SKILL.md not found"]
    text = skill_md.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(lines) > max_lines:
        errors.append(f"SKILL.md {len(lines)} 行，超过 {max_lines} 行上限")
    for section in SECTIONS:
        if section not in text:
            errors.append(f"缺少五段式章节 {section}")

    if "## Gotchas" in text:
        tail = text.split("## Gotchas", 1)[1]
        bullets = [l for l in tail.splitlines() if l.strip().startswith("- ")]
        if len(bullets) < 4:
            errors.append(f"Gotchas 仅 {len(bullets)} 条，要求 >=4")
    steps = re.findall(r"^### Step\s+\d+", text, re.M)
    if not (3 <= len(steps) <= 8):
        errors.append(f"工作流步骤数 {len(steps)} 不在 3-8 之间")
    if text.count("\n---\n") < 3:
        errors.append("章节间缺少 --- 分隔")

    for name in FORBIDDEN_FILES:
        if (skill_dir / name).exists():
            errors.append(f"技能包内禁止出现 {name}")
    if (skill_dir / "slices").exists():
        errors.append("技能包内禁止出现 slices/ 拷贝")

    refs = list((skill_dir / "references").glob("*.md")) if (skill_dir / "references").exists() else []
    for ref in refs:
        if "何时读本文件" not in ref.read_text(encoding="utf-8"):
            errors.append(f"{ref.name} 缺少「何时读本文件」说明")
    if "/Users/" in text or "/home/" in text:
        errors.append("SKILL.md 内出现绝对路径；references 必须使用相对路径")
    if not re.search(r"references/[^\s`)]+\.md", text):
        errors.append("SKILL.md 未用相对路径引用 references/ 分片")
    return errors
