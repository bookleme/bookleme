"""Idempotent installation into the single source of truth.

Only location outside the workspace we are allowed to write to.
"""

from __future__ import annotations

import os
import shutil
from datetime import datetime, timezone
from pathlib import Path

from ..config import SKILLS_ROOT
from ..hashing import sha256_file

CLAUDE_SKILLS = Path(os.environ.get("BOOKLEME_CLAUDE_SKILLS", str(Path.home() / ".claude/skills")))


def target_for(category: str, display_name: str, slug: str) -> Path:
    """安装目标路径（先算出来，才能在动手前一次性查完冲突）。"""
    return SKILLS_ROOT / category / f"{display_name}（{slug}）"


def preflight(entries: list[dict]) -> None:
    """全部目标先查一遍：宁可一个都不装，也不要装了一半才发现冲突。"""
    conflicts = []
    for e in entries:
        target = target_for(e["category"], e["display_name"], e["slug"])
        if not os.path.lexists(target):
            continue
        existing = target / "SKILL.md"
        incoming = Path(e["skill_dir"]) / "SKILL.md"
        same = (existing.exists() and incoming.exists()
                and sha256_file(existing) == sha256_file(incoming))
        if not same:
            conflicts.append(str(target))
    if conflicts:
        raise FileExistsError("目标已存在且内容不同，拒绝覆盖：" + "、".join(conflicts))


def install_skill(skill_dir: Path, *, category: str, display_name: str, slug: str,
                  frontmatter_name: str, distribution: str = "private") -> dict:
    skill_dir = Path(skill_dir)
    folder = f"{display_name}（{slug}）"  # 全角括号，本机约定
    target = SKILLS_ROOT / category / folder
    receipts: list[str] = []

    if os.path.lexists(target):
        existing = target / "SKILL.md"
        incoming = skill_dir / "SKILL.md"
        if existing.exists() and incoming.exists() and sha256_file(existing) == sha256_file(incoming):
            receipts.append("target exists with identical SKILL.md; skipped")
        else:
            raise FileExistsError(f"目标已存在且内容不同，拒绝覆盖：{target}")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(skill_dir, target)
        receipts.append(f"written to {target}")

    # ~/.workbuddy/skills 与 ~/.codex/skills 是整目录软链接 → 自动可见，绝不改动。
    link = CLAUDE_SKILLS / folder
    if CLAUDE_SKILLS.exists():
        if os.path.lexists(link):
            if Path(os.readlink(link)) != target:
                raise FileExistsError(f"Claude 软链接已存在且指向不同：{link}")
            receipts.append("claude symlink already correct; skipped")
        else:
            os.symlink(str(target), str(link))
            receipts.append(f"claude symlink created: {link} -> {target}")
    else:
        receipts.append("~/.claude/skills not present; skipped")

    return {
        "target_abs": str(target),
        "symlink_abs": str(link),
        "frontmatter_name": frontmatter_name,
        "validate_passed": True,
        "distribution": distribution,
        "actions": receipts,
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
