"""Dependency-free equivalent of the official quick_validate.py.

Verified line-by-line against the official validator shipped in the skill
source of truth at `<SKILLS_ROOT>/.system/skill-creator/scripts/quick_validate.py`
(resolve `SKILLS_ROOT` from `bookleme.config`, or set `BOOKLEME_SKILLS_ROOT`).
Key rules there: frontmatter whitelist, name regex, description limits, TODO scan.
When PyYAML is available the official script is ALSO run by pipeline.py as a second opinion.
"""

from __future__ import annotations

import re
from pathlib import Path

ALLOWED_KEYS = {"name", "description", "license", "allowed-tools", "metadata"}


def _parse_frontmatter(text: str) -> tuple[dict | None, str, str]:
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    if not m:
        return None, "", "未找到合法 YAML frontmatter（须以 --- 开头）"
    data: dict = {}
    for line in m.group(1).splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            return None, "", f"frontmatter 行无法解析: {line!r}"
        key, _, value = line.partition(":")
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        data[key] = value
    return data, text[m.end():], ""


def validate_text(text: str) -> list[str]:
    data, body, err = _parse_frontmatter(text)
    errors: list[str] = []
    if err:
        return [err]
    if not isinstance(data, dict):
        return ["frontmatter 必须是 YAML 字典"]

    unexpected = set(data) - ALLOWED_KEYS
    if unexpected:
        errors.append(f"Unexpected key(s) in SKILL.md frontmatter: {', '.join(sorted(unexpected))}")
    for key in ("name", "description"):
        if key not in data:
            errors.append(f"Missing '{key}' in frontmatter")

    name = str(data.get("name", "")).strip()
    if name:
        if not re.fullmatch(r"[a-z0-9-]+", name):
            errors.append(f"Name '{name}' should be hyphen-case")
        if name.startswith("-") or name.endswith("-") or "--" in name:
            errors.append(f"Name '{name}' cannot start/end with hyphen or contain consecutive hyphens")
        if len(name) > 64:
            errors.append(f"Name is too long ({len(name)} characters)")

    desc = str(data.get("description", "")).strip()
    if desc.startswith("[TODO:"):
        errors.append("Description contains an unfinished TODO placeholder")
    if "<" in desc or ">" in desc:
        errors.append("Description cannot contain angle brackets")
    if len(desc) > 1024:
        errors.append(f"Description is too long ({len(desc)} characters)")

    fence = None
    for line in body.splitlines():
        fm = re.match(r"^[ \t]*(?:(?:[-+*]|\d+[.)])[ \t]+)?(`{3,}|~{3,})(.*)$", line)
        if fm:
            marker = fm.group(1)
            if fence is None:
                fence = marker[0]
            elif marker[0] == fence and not fm.group(2).strip():
                fence = None
            continue
        if fence is None and re.fullmatch(r"[ ]{0,3}\[TODO:[^\n]*\][ \t]*", line):
            errors.append("Skill instructions contain an unfinished TODO placeholder")
    return errors


def validate_skill(skill_dir: Path) -> list[str]:
    path = Path(skill_dir) / "SKILL.md"
    if not path.exists():
        return ["SKILL.md not found"]
    return validate_text(path.read_text(encoding="utf-8"))
